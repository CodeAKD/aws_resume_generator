# lambda_function.py  (presign-upload: PUT + GET)
import os, json, urllib.parse, boto3, traceback
from botocore.client import Config

# Let boto3 auto-detect region (Lambda sets AWS_REGION automatically)
session = boto3.session.Session()
REGION = session.region_name   # <-- SAFE, no env vars needed

BUCKET = os.environ.get('BUCKET_NAME')   # your bucket name only
EXPIRY = int(os.environ.get('PRESIGN_EXPIRY', '300'))

s3 = boto3.client('s3', config=Config(signature_version='s3v4'))

def proxy_response(status, body):
    return {
        "statusCode": int(status),
        "headers": {
            "Content-Type":"application/json",
            "Access-Control-Allow-Origin":"*",
            "Access-Control-Allow-Credentials":"true"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    try:
        if not BUCKET:
            return proxy_response(500, {"message":"Missing BUCKET_NAME env var"})

        # Read inputs
        params = event.get('queryStringParameters') or {}
        filename = params.get('filename')
        content_type = params.get('contentType')

        if not filename:
            # support JSON body
            body = event.get('body')
            if isinstance(body, str) and body:
                try: body_json = json.loads(body)
                except: body_json = {}
            else:
                body_json = body or {}

            filename = body_json.get("filename") or filename
            content_type = body_json.get("contentType") or content_type

        if not filename:
            return proxy_response(400, {"message":"filename required (query param or JSON body)"})

        # Sanitize
        filename = urllib.parse.unquote(filename).replace("..","").lstrip("/")
        key = f"uploads/{filename}"

        # PUT presign
        put_params = {'Bucket': BUCKET, 'Key': key}
        if content_type:
            put_params["ContentType"] = content_type

        upload_url = s3.generate_presigned_url(
            "put_object",
            Params=put_params,
            ExpiresIn=EXPIRY,
            HttpMethod="PUT"
        )

        # GET presign (for preview)
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=EXPIRY,
            HttpMethod="GET"
        )

        # Permanent object path
        object_url = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{key}"

        return proxy_response(200, {
            "uploadUrl": upload_url,
            "downloadUrl": download_url,
            "objectUrl": object_url,
            "key": key
        })

    except Exception as e:
        tb = traceback.format_exc()
        return proxy_response(500, {
            "message": "failed to generate presigned url",
            "error": str(e),
            "traceback_last_lines": tb.splitlines()[-15:]
        })
