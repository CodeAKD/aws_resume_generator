import os, json, urllib.parse, boto3, traceback
from botocore.client import Config

session = boto3.session.Session()
REGION = session.region_name
BUCKET = os.environ.get('BUCKET_NAME')
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
        params = event.get('queryStringParameters') or {}
        key = params.get('key')
        object_url = params.get('objectUrl')
        if not key and object_url:
            parsed = urllib.parse.urlsplit(object_url)
            key = parsed.path.lstrip('/') if parsed.path else None
        if not key:
            return proxy_response(400, {"message":"Missing key (use ?key=uploads/...) or objectUrl"})
        key = urllib.parse.unquote(key).lstrip('/')
        url = s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=EXPIRY, HttpMethod='GET')
        return proxy_response(200, {"downloadUrl": url, "key": key})
    except Exception as e:
        tb = traceback.format_exc()
        return proxy_response(500, {"message":"failed to generate presigned get", "error":str(e), "traceback_last_lines": tb.splitlines()[-15:]})
