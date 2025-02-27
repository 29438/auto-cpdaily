import base64
import json
import random
import rsa
import sys
import yaml
from io import BytesIO
from Crypto.Cipher import AES
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ocr.v20181119 import ocr_client, models
from datetime import datetime, timedelta, timezone
from requests_toolbelt import MultipartEncoder


class Utils:
    def __init__(self):
        pass

    # 获取指定长度的随机字符
    @staticmethod
    def randString(length):
        baseString = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
        data = ''
        for i in range(length):
            data += baseString[random.randint(0, len(baseString) - 1)]
        return data

    @staticmethod
    def getYmlConfig(yaml_file='config.yml'):
        file = open(yaml_file, 'r', encoding="utf-8")
        file_data = file.read()
        file.close()
        config = yaml.load(file_data, Loader=yaml.FullLoader)
        return dict(config)

    # aes加密的实现
    @staticmethod
    def encryptAES(password, key):
        randStrLen = 64
        randIvLen = 16
        ranStr = Utils.randString(randStrLen)
        ivStr = Utils.randString(randIvLen)
        aes = AES.new(bytes(key, encoding='utf-8'), AES.MODE_CBC,
                      bytes(ivStr, encoding="utf8"))
        data = ranStr + password

        text_length = len(data)
        amount_to_pad = AES.block_size - (text_length % AES.block_size)
        if amount_to_pad == 0:
            amount_to_pad = AES.block_size
        pad = chr(amount_to_pad)
        data = data + pad * amount_to_pad

        text = aes.encrypt(bytes(data, encoding='utf-8'))
        text = base64.encodebytes(text)
        text = text.decode('utf-8').strip()
        return text

    # 通过url解析图片验证码
    @staticmethod
    def getCodeFromImg(res, imgUrl):
        Utils.log('开始识别验证码')
        response = res.get(imgUrl, verify=False)  # 将这个图片保存在内存
        # 得到这个图片的base64编码
        imgCode = str(base64.b64encode(BytesIO(response.content).read()),
                      encoding='utf-8')
        # print(imgCode)
        try:
            cred = credential.Credential(
                Utils.getYmlConfig()['ocrOption']['SecretId'],
                Utils.getYmlConfig()['ocrOption']['SecretKey'])
            httpProfile = HttpProfile()
            httpProfile.endpoint = "ocr.tencentcloudapi.com"

            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = ocr_client.OcrClient(cred, "ap-beijing", clientProfile)

            req = models.GeneralBasicOCRRequest()
            params = {"ImageBase64": imgCode}
            req.from_json_string(json.dumps(params))
            resp = client.GeneralBasicOCR(req)
            codeArray = json.loads(resp.to_json_string())['TextDetections']
            code = ''
            for item in codeArray:
                code += item['DetectedText'].replace(' ', '')
            if len(code) == 4:
                Utils.log('识别验证码成功')
                return code
            else:
                Utils.log('识别结果不正确正在重试')
                return Utils.getCodeFromImg(res, imgUrl)
        except TencentCloudSDKException as err:
            raise Exception('验证码识别出现问题了' + str(err.message))

    @staticmethod
    def encryptRSA(message, m, e):
        mm = int(m, 16)
        ee = int(e, 16)
        rsa_pubkey = rsa.PublicKey(mm, ee)
        crypto = Utils._encrypt_rsa(message.encode(), rsa_pubkey)
        return crypto.hex()

    @staticmethod
    def _pad_for_encryption_rsa(message, target_length):
        message = message[::-1]
        max_msglength = target_length - 11
        msglength = len(message)
        padding = b''
        padding_length = target_length - msglength - 3
        for i in range(padding_length):
            padding += b'\x00'
        return b''.join([b'\x00\x00', padding, b'\x00', message])

    @staticmethod
    def _encrypt_rsa(message, pub_key):
        keylength = rsa.common.byte_size(pub_key.n)
        padded = Utils._pad_for_encryption_rsa(message, keylength)
        payload = rsa.transform.bytes2int(padded)
        encrypted = rsa.core.encrypt_int(payload, pub_key.e, pub_key.n)
        block = rsa.transform.int2bytes(encrypted, keylength)
        return block

    @staticmethod
    def log(content):
        print(Utils.getTimeStr() + " V%s %s" %
              (Utils.getYmlConfig()['Version'], content))
        sys.stdout.flush()

    @staticmethod
    def getTimeStr():
        utc_dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        bj_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
        return bj_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 上传图片到阿里云oss
    @staticmethod
    def uploadPicture(env, type, picSrc):
        url = f'{env.host}wec-counselor-{type}-apps/stu/oss/getUploadPolicy'
        res = env.session.post(url=url,
                               headers={'content-type': 'application/json'},
                               data=json.dumps({'fileType': 1}),
                               verify=False)
        datas = res.json().get('datas')
        fileName = datas.get('fileName')
        policy = datas.get('policy')
        accessKeyId = datas.get('accessid')
        signature = datas.get('signature')
        policyHost = datas.get('host')
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:50.0) Gecko/20100101 Firefox/50.0'
        }
        multipart_encoder = MultipartEncoder(
            fields={  # 这里根据需要进行参数格式设置
                'key': fileName,
                'policy': policy,
                'OSSAccessKeyId': accessKeyId,
                'success_action_status': '200',
                'signature': signature,
                'file': ('blob', open(picSrc, 'rb'), 'image/jpg')
            })
        headers['Content-Type'] = multipart_encoder.content_type
        env.session.post(url=policyHost,
                         headers=headers,
                         data=multipart_encoder)
        env.fileName = fileName

    # 获取图片上传位置
    @staticmethod
    def getPictureUrl(env, type):
        url = f'{env.host}wec-counselor-{type}-apps/stu/{type}/previewAttachment'
        params = {'ossKey': env.fileName}
        res = env.session.post(url=url,
                               headers={'content-type': 'application/json'},
                               data=json.dumps(params),
                               verify=False)
        photoUrl = res.json().get('datas')
        return photoUrl