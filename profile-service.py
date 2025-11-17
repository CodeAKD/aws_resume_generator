# lambda_function.py
import os
import json
import traceback
import boto3

# ---------- Configuration from environment ----------
TABLE_NAME = os.environ.get('TABLE_NAME')            # required
PRIMARY_KEY = os.environ.get('PRIMARY_KEY', 'PK')   # will be 'PK'
SORT_KEY = os.environ.get('SORT_KEY', 'SK')         # will be 'SK'
REGION = os.environ.get('AWS_REGION') or 'us-east-1'

# ---------- DynamoDB init ----------
dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = None
if TABLE_NAME:
    table = dynamodb.Table(TABLE_NAME)

# ---------- Helpers ----------
def proxy_response(status_code, body_obj):
    return {
        "statusCode": int(status_code),
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true"
        },
        "body": json.dumps(body_obj)
    }

def safe_parse_body(event):
    body = event.get('body')
    if body is None:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except Exception:
            # malformed JSON -> return empty dict to avoid crash
            return {}
    if isinstance(body, dict):
        return body
    return {}

def get_cognito_sub(event):
    # prefer Cognito authorizer claims.sub
    try:
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {}) or {}
        return claims.get('sub') or claims.get('username')
    except Exception:
        return None

def build_pk_for_user(sub):
    # canonical PK form: USER#<sub>
    return f"USER#{sub}"

def ensure_keys_for_profile(item, user_sub):
    """
    Ensure item includes PK and SK. If missing, populate them.
    Returns (ok, message, item)
    """
    # If PK present, keep it; else use user_sub
    if PRIMARY_KEY in item and item[PRIMARY_KEY]:
        pk = item[PRIMARY_KEY]
    elif user_sub:
        pk = build_pk_for_user(user_sub)
        item[PRIMARY_KEY] = pk
    else:
        return False, f"Missing primary key {PRIMARY_KEY} and no Cognito sub provided", item

    # SK: we will use a fixed SK 'PROFILE' for each user's profile entry
    profile_sk_value = item.get(SORT_KEY) or "PROFILE"
    item[SORT_KEY] = profile_sk_value

    return True, None, item

# ---------- Core logic ----------
def lambda_inner(event, context):
    # Determine HTTP method (support both v1 REST and v2 http API structures)
    method = (event.get('httpMethod') or '').upper()
    if not method:
        method = (event.get('requestContext', {}).get('http', {}) or {}).get('method', '').upper()

    # GET -> fetch profile by PK/PROFILE
    if method == 'GET':
        user_sub = get_cognito_sub(event)
        if not user_sub:
            return proxy_response(401, {"message": "Unauthorized - no Cognito sub found"})
        if table is None:
            return proxy_response(500, {"message": "Server misconfigured: TABLE_NAME env var missing"})
        key = {PRIMARY_KEY: build_pk_for_user(user_sub), SORT_KEY: "PROFILE"}
        resp = table.get_item(Key=key)
        item = resp.get('Item')
        return proxy_response(200, item or {})

    # POST -> create/update profile (one item per user, SK=PROFILE)
    elif method == 'POST':
        user_sub = get_cognito_sub(event)
        body = safe_parse_body(event)
        if not isinstance(body, dict):
            return proxy_response(400, {"message": "Bad Request: body must be a JSON object"})
        if not user_sub and not body.get(PRIMARY_KEY):
            return proxy_response(401, {"message": "Unauthorized - no Cognito sub and no primary key in body"})

        ok, msg, item = ensure_keys_for_profile(body, user_sub)
        if not ok:
            return proxy_response(400, {"message": msg})

        if table is None:
            return proxy_response(500, {"message": "Server misconfigured: TABLE_NAME env var missing"})

        # Optionally sanitize/normalize item here (e.g., remove empty arrays)
        # Put item (overwrite existing profile for the user)
        table.put_item(Item=item)
        return proxy_response(200, {"ok": True})

    else:
        return proxy_response(405, {"message": "Method not allowed"})

def lambda_handler(event, context):
    try:
        return lambda_inner(event, context)
    except Exception as e:
        tb = traceback.format_exc()
        print("UNHANDLED ERROR:", tb)
        return proxy_response(500, {
            "message": "Internal server error",
            "error": str(e),
            "traceback_last_lines": tb.splitlines()[-10:]
        })
