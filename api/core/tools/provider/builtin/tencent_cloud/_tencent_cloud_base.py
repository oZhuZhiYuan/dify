# -*- coding: utf-8 -*-
import hashlib
import hmac
import time
from datetime import datetime
import json
from http.client import HTTPSConnection

class SignatureBuilder(object):

    def __init__(self, service, secret_id, secret_key):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.service = service
        self.algorithm = "TC3-HMAC-SHA256"

    def _sign(self, key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def get_authorization_header(self, timestamp, host, action, payload):
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        # ************* 步骤 1：拼接规范请求串 *************
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (http_request_method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)

        # ************* 步骤 2：拼接待签名字符串 *************
        credential_scope = date + "/" + self.service + "/" + "tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = (self.algorithm + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)

        # ************* 步骤 3：计算签名 *************
        secret_date = self._sign(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = self._sign(secret_date, self.service)
        secret_signing = self._sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        # ************* 步骤 4：拼接 Authorization *************
        authorization = (self.algorithm + " " +
                        "Credential=" + self.secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)
        
        return authorization

class YunApiClient(object):

    def __init__(self, host, service, version ,secret_id, secret_key, region, user_id=None):
        self.host = host
        self.service = service
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.user_id = user_id
        self.version = version
        self.region = region

        self.signature_builder = SignatureBuilder(
            service, secret_id, secret_key)

    def send(self, action, payload):
        payload = json.dumps(payload)
        timestamp = int(time.time())
        headers = {
            'Authorization': self.signature_builder.get_authorization_header(timestamp, self.host, action, payload),
            "Content-Type": "application/json; charset=utf-8",
            'Host': self.host,
            'X-TC-Action': action,
            'X-TC-Timestamp': timestamp,
            'X-TC-Version': self.version,
            'X-TC-Region': self.region,
            'X-TC-Language': 'zh-CN',
        }
        if self.user_id:
            headers['x-qcloud-user-id'] = str(self.user_id)

        req = HTTPSConnection(self.host)
        req.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        print(f"call {action}, headers: {headers}, payload: {payload}")
        resp = req.getresponse()
        ret = json.loads(resp.read())
        return ret

