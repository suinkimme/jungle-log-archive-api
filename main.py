# 내장
import json
from functools import wraps
from datetime import datetime, timezone, timedelta
import os
import subprocess
import sys

# 패키지 자동 설치
def install_requirements():
    try:
        subprocess.check_call(["pip", "install", "-r", "requirements.txt"])
    except subprocess.CalledProcessError as e:
        print(f"패키지 설치 중 오류 발생: {e}")
        sys.exit(1)

# requirements.txt가 있으면 패키지 설치
if os.path.exists("requirements.txt"):
    install_requirements()

# 외부
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from flask.json.provider import JSONProvider
from bson import ObjectId
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

load_dotenv()

app = Flask(__name__)
CORS(app)

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DB")]

# 한국 시간대 설정
KST = timezone(timedelta(hours=9))


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.strftime('%Y-%m-%d %H:%M:%S')
        return json.JSONEncoder.default(self, o)


class CustomJSONProvider(JSONProvider):
    def dumps(self, obj, **kwargs):
        return json.dumps(obj, **kwargs, cls=CustomJSONEncoder)

    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)


app.json = CustomJSONProvider(app)

# meta 정보 가져오기
def get_meta_tags(url):
    try:
        # 웹 페이지 요청
        response = requests.get(url)
        response.raise_for_status()

        # BeautifulSoup으로 HTML 파싱
        soup = BeautifulSoup(response.text, 'html.parser')

        # 메타 태그 추출
        description = soup.find('meta', {'name': 'description'})
        og_title = soup.find('meta', {'property': 'og:title'})
        og_image = soup.find('meta', {'property': 'og:image'})
        og_url = soup.find('meta', {'property': 'og:url'})

        # 결과를 딕셔너리로 구성
        return {
            "description": description['content'] if description else None,
            "og_title": og_title['content'] if og_title else None,
            "og_image": og_image['content'] if og_image else None,
            "og_url": og_url['content'] if og_url else None
        }

    except Exception as e:
        print(f"메타 태그 추출 중 에러 발생: {e}")
        return None

# API 응답 일관된 형식으로 반환
def api_response(data=None, message=None, status=200):
    return jsonify({
        'result': 'success' if status < 400 else 'fail',
        **({'data': data} if data is not None else {}),
        **({'message': message} if message is not None else {})
    }), status


# API 요청 검사 데코레이터
def validate_request(required_fields, optional_fields=None):
    optional_fields = optional_fields or {}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # JSON 요청인지 확인
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return api_response(message="요청 형식이 올바르지 않습니다.", status=400)

            # 필수 입력 값 검사
            missing_fields = [
                field for field in required_fields if data.get(field) is None]
            if missing_fields:
                return api_response(message=f"필수 입력값이 누락되었습니다: {', '.join(missing_fields)}", status=400)

            # 데이터 타입 검사
            combined_fields = {**required_fields, **optional_fields}
            for field, field_type in combined_fields.items():
                # 선택 필드는 값이 존재할 때만 검사함
                if field in data and data[field] is not None:
                    if not isinstance(data[field], field_type):
                        return api_response(message=f"{field}의 타입이 올바르지 않습니다.", status=400)

                    # 빈 문자열 검사
                    if field_type == str and data[field].strip() == "":
                        return api_response(message=f"{field}은 빈 문자열을 허용하지 않습니다.", status=400)

            return func(data, *args, **kwargs)
        return wrapper

    return decorator

@app.route('/')
def render_index():
    return "connected"

@app.route('/api/logs', methods=['POST'])
@validate_request({'name': str, 'url': str})
def insert_til(data):
    try:
        name = data.get('name')
        url = data.get('url')

        junglers = [
            '고민지', '김기래', '김동규', '김민규', '김보아', '김성종', '김수민', '김현호',
            '류승찬', '박수연', '박혜린', '배상화', '송상록', '신예린', '신우진', '안수연',
            '안준표', '안태주', '양진성', '오준탁', '유호준', '이종호', '이주명', '이주형',
            '이지윤', '이태윤', '장준영', '조성진', '최선하', '한진우', '홍석표', '황희구'
        ]

        if name not in junglers:
            return api_response(message='멤버가 아닙니다.', status=400)

        # 메타 태그 정보 추출
        meta_info = get_meta_tags(url)

        new_til = {
            'name': name,
            'url': url,
            'created_at': datetime.now(),
            'trash': False,
            'meta_info': meta_info if meta_info else {}
        }
        result = db.logs.insert_one(new_til)
        return api_response({'inserted_id': str(result.inserted_id)}, status=200)
    except Exception as e:
        return api_response(message='Log 남기기에 실패했습니다.', status=404)

@app.route('/api/logs')
def list_til():
    try:
        # GET 파라미터에서 page 가져오기
        page = request.args.get('page', '1')
        
        # page가 숫자인지 확인
        try:
            page = int(page)
            if page < 1:
                page = 1
        except ValueError:
            page = 1

        # 페이지당 항목 수
        per_page = 10
        
        # 검색 조건 설정
        query = {'trash': False}

        # 전체 문서 수 계산
        total_docs = db.logs.count_documents(query)
        total_pages = (total_docs + per_page - 1) // per_page

        # MongoDB에서 TIL 목록 조회
        logs = list(db.logs.find(
            query,
            {'_id': 1, 'name': 1, 'url': 1, 'created_at': 1, 'meta_info': 1}
        ).sort('created_at', -1).skip((page - 1) * per_page).limit(per_page))

        return api_response(data={
            'logs': logs,
            'finished': page >= total_pages
        }, status=200)
    except Exception as e:
        print(e)
        return api_response(message='TIL 목록 조회에 실패했습니다.', status=404)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)