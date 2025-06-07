# 내장
import json
from functools import wraps
from datetime import datetime, timezone, timedelta
import os
import subprocess
import sys
import re

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
from flask import Flask, request, jsonify, session, redirect, url_for
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

app.secret_key = os.getenv('FLASK_SECRET_KEY')

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DB")]

# 한국 시간대 설정
KST = timezone(timedelta(hours=9))

# GIT 정보
GITHUB_AUTH_BASE_URL = os.getenv('GITHUB_AUTH_BASE_URL')
GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID')
GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET')
GITHUB_USER_API = os.getenv('GITHUB_USER_API')
GITHUB_TOKEN_URL = os.getenv('GITHUB_TOKEN_URL')


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

# 멤버 검증
def is_valid_jungler(name):
    junglers = [
        '고민지', '김기래', '김동규', '김민규', '김보아', '김성종', '김수민', '김현호',
        '류승찬', '박수연', '박혜린', '배상화', '송상록', '신예린', '신우진', '안수연',
        '안준표', '안태주', '양진성', '오준탁', '유호준', '이종호', '이주명', '이주형',
        '이지윤', '이태윤', '장준영', '조성진', '최선하', '한진우', '홍석표', '황희구'
    ]
    return name in junglers


# 사이트 구별
def get_site_info(url):
    
    if not url:
        return {"status": "error", "message": "URL이 없습니다."}

    try:
        response = requests.get(url)
        content = response.text

        # Tistory 블로그 확인
        if '"TOP_SSL_URL":"https://www.tistory.com"' in content:

            # script 태그에서 window.T.config 설정 찾기
            config_match = re.search(r'window\.T\.config\s*=\s*({[^;]+});', content)
            
            if config_match:
                config_str = config_match.group(1)
                # JSON으로 파싱
                config = json.loads(config_str)
                name = config['BLOG']['name']
                id = config['BLOG']['id']
                p_url = f'https://{name}.tistory.com/m/api/entry/0/POST?page=#page&size=20'
                p_page = 0
                posts = []
                return {"status": "success", "message": "블로그 조회에 성공 하였습니다.", "type": "tistory", "name": name, "id": id, "p_url": p_url, "p_page": p_page, "posts": posts}
            return {"status": "error", "message": "블로그 조회에 실패했습니다."}
        elif 'velog.io/@' in url:
            # velog 아이디 추출
            velog_pattern = r'https://velog\.io/(@[^/]+)'
            velog_match = re.search(velog_pattern, url)
            id = velog_match.group(1)[1:]
            name = id
            p_url = "{\"query\":\"\\n    query velogPosts($input: GetPostsInput!) {\\n  posts(input: $input) {\\n    id\\n    title\\n    short_description\\n    thumbnail\\n    user {\\n      id\\n      username\\n      profile {\\n        id\\n        thumbnail\\n        display_name\\n      }\\n    }\\n    url_slug\\n    released_at\\n    updated_at\\n    comments_count\\n    tags\\n    is_private\\n    likes\\n  }\\n}\\n    \",\"variables\":{\"input\":{\"cursor\":\"#cursor\",\"username\":\"#id\",\"limit\":100,\"tag\":\"\"}}}"
            p_page = ""
            posts = []
            if id:
                return {"status": "success", "message": "블로그 조회에 성공 하였습니다.", "type": "velog", "name":name, "id": id, "p_url": p_url, "p_page": p_page, "posts": posts}
            return {"status": "success", "message": "블로그 조회에 성공 하였습니다.", "type": "velog"}
        return {"status": "error", "message": "블로그 조회에 실패했습니다."}
    except:
        return {"status": "error", "message": "블로그 조회에 실패했습니다."}

# 사이트 정보 가져오기
def get_posts(site_info):
    if site_info['type'] == 'tistory':
        page = site_info['p_page']
        p_url = site_info['p_url'].replace('#page', str(page))
        response = requests.get(p_url).json()
        for row in response["data"]['items']:
            item = {
                "id": row['id'],
                "title": row['title'],
                "url": row['url']+row['subPath'],
                "created_at": datetime.strptime(row['published'], '%Y. %m. %d.').strftime('%Y-%m-%d'),
                "thumbnail": row['thumbnail'],
                "summary": row['summary']
            }
            site_info['posts'].append(item)
        if response['data']['nextPage'] != None:
            site_info['p_page'] = page + 1
            return get_posts(site_info)
    elif site_info['type'] == 'velog':
        payload = site_info['p_url'].replace('#cursor', site_info['p_page']).replace('#id', site_info['id'])
        headers = {'content-type': 'application/json'}

        response = requests.request("POST", "https://v3.velog.io/graphql", headers=headers, data=payload).json()
        
        for row in response['data']['posts']:
            item = {
                "id": row['id'],
                "title": row['title'],
                "url": f"https://velog.io/@{site_info['id']}/{row['url_slug']}",
                "created_at": row['released_at'],
                "thumbnail": row['thumbnail'],
                "summary": row['short_description']
            }
            site_info['p_page'] = row['id']
            site_info['posts'].append(item)
            
        if response['data']['posts'] != []:
            return get_posts(site_info)
        
    return site_info



@app.route('/')
def index():
    user = session.get('user')
    if user:
        user_json = json.dumps(user, indent=2, ensure_ascii=False)
        html = f"현재 로그인된 사용자 정보:<pre>{user_json}</pre>"
        return html
    return '<a href="/login">Login with GitHub</a>'

"""
    @API: GET /login
    @Description: 깃허브 OAuth 인증 페이지로 리다이렉트

    @Response:
        성공 (200):
            - 깃허브 OAuth 인증 페이지로 리다이렉트
"""
@app.route('/login')
def login():
    return redirect(f'{GITHUB_AUTH_BASE_URL}?client_id={GITHUB_CLIENT_ID}&scope=read:org')


"""
    @API: GET /auth/login
    @Description: 깃허브 인증 후 콜백 처리 및 세션에 사용자 정보 저장

    @Response:
        - 성공 (200):
            - 세션에 사용자 정보 저장
            - 메인 페이지로 리다이렉트
"""
@app.route('/auth/login')
def callback():
    code = request.args.get('code')
    token_res = requests.post(
        GITHUB_TOKEN_URL,
        headers={'Accept': 'application/json'},
        data={
            'client_id': GITHUB_CLIENT_ID,
            'client_secret': GITHUB_CLIENT_SECRET,
            'code': code
        }
    )
    token_json = token_res.json()
    access_token = token_json.get('access_token')
    user_res = requests.get(
        GITHUB_USER_API,
        headers={'Authorization': f'token {access_token}'}
    )
    session['user'] = user_res.json()
    return redirect(url_for('index'))


"""
    @API: GET /logout
    @Description: 세션 초기화

    @Response:
        - 성공 (200):
            - 세션 초기화
            - 메인 페이지로 리다이렉트
"""
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))




"""
@API: POST /api/logs
@Description: 정글의 TIL(Today I Learned) 로그를 생성하는 API

@Request Body:
    - name(string): 정글 이름
    - url(string): TIL 게시글 URL

@Validation:
    - name: 정글 명단에 있는 이름만 허용
    - url: 유효한 URL 형식 필요

@Response:
    성공 (200):
        - inserted_id: 생성된 문서의 ObjectId
    실패 (400):
        - 멤버가 아닌 경우
    실패 (404): 
        - 서버 에러 발생 시

@Features:
    - URL의 메타 정보 자동 추출
    - 생성 시간 자동 기록
    - Soft Delete 지원 (trash 필드)
"""
@app.route('/api/logs', methods=['POST'])
@validate_request({'name': str, 'url': str})
def insert_til(data):
    try:
        name = data.get('name')
        url = data.get('url')

        if not is_valid_jungler(name):
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


"""
@API: GET /api/logs
@Description: 정글의 TIL(Today I Learned) 로그를 조회하는 API

@Request Body:
    - page(int): 페이지 번호

@Validation:
    - page: 페이지 번호

@Response:
    성공 (200):
        - logs: 로그 목록
        - finished: 마지막 페이지 여부
    실패 (404): 
        - 서버 에러 발생 시

@Features:
    - 페이지당 10개씩 조회
"""
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


"""
@API: GET /api/logs
@Description: 정글의 TIL(Today I Learned) 로그를 조회하는 API

@Request Body:
    - name(string): 정글 이름
    - url(string): 블로그 주소

@Validation:
    - name: 정글 명단에 있는 이름만 허용
    - url: 유효한 URL 형식 필요

@Response:
    성공 (200):
        - 블로그 타입
        - 블로그 이름
        - 블로그 아이디
        - 블로그 포스트 주소
    실패 (404): 
        - 서버 에러 발생 시

@Features:
    - 블로그 타입에 따라 포스트 조회
"""
@app.route('/api/posts', methods=['POST'])
@validate_request({'name': str, 'url': str})
def posts(data):
    try:
        name = data.get('name')
        url = data.get('url')

        site_info = get_site_info(url)

        if site_info == None or site_info['status'] == 'error':
            return api_response(message='사이트 타입을 찾을 수 없습니다.', status=400)
        
        site_posts = get_posts(site_info)
        result = site_posts['posts']
        

        if not is_valid_jungler(name):
            return api_response(message='멤버가 아닙니다.', status=400)
        
        return api_response(result, status=200)
    except Exception as e:
        print(e)
        return api_response(message='TIL 목록 조회에 실패했습니다.', status=404)



if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)