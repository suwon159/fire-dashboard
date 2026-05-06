import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import math
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="건설현장 화재위험도 대시보드", layout="wide")


# =========================================================
# 화면 압축 CSS
# =========================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2.0rem;
        padding-bottom: 1rem;
        max-width: 1500px;
    }

    section[data-testid="stSidebar"] {
        width: 300px !important;
    }

    section[data-testid="stSidebar"] > div {
        padding-top: 1.2rem;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }

    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.35rem;
    }

    section[data-testid="stSidebar"] label {
        font-size: 0.85rem !important;
        margin-bottom: 0.15rem !important;
    }

    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        margin-top: 0.3rem !important;
        margin-bottom: 0.5rem !important;
    }

    section[data-testid="stSidebar"] div[data-baseweb="select"] {
        min-height: 2.2rem;
    }

    section[data-testid="stSidebar"] input {
        min-height: 2.2rem;
        font-size: 0.85rem;
    }

    section[data-testid="stSidebar"] button {
        min-height: 2.2rem;
        padding-top: 0.25rem;
        padding-bottom: 0.25rem;
    }

    section[data-testid="stSidebar"] .stAlert {
        padding: 0.4rem 0.6rem;
        font-size: 0.82rem;
    }

    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        font-size: 0.78rem;
        line-height: 1.25;
    }

    div[data-testid="stMetric"] {
        background-color: #ffffff;
        padding: 8px 10px;
        border-radius: 10px;
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.7rem;
    }

    .stride-box {
        background-color:#34495e;
        padding:16px;
        border-radius:10px;
        color:white;
        font-size:17px;
        font-weight:bold;
        text-align:center;
        line-height:1.65;
    }

    .recommend-box {
        padding:24px;
        border-radius:10px;
        color:white;
        font-size:22px;
        font-weight:bold;
        text-align:center;
        line-height:1.8;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .small-info-box {
        background-color: #eaf4ff;
        border: 2px solid #3498db;
        border-radius: 12px;
        padding: 14px 12px;
        color: #1f2d3d;
        margin-top: 6px;
        margin-bottom: 8px;
        text-align: center;
    }

    .small-info-title {
        font-size: 0.9rem;
        font-weight: 700;
        color: #566573;
        margin-bottom: 4px;
    }

    .small-info-main {
        font-size: 1.45rem;
        font-weight: 900;
        line-height: 1.35;
    }

    .small-info-sub {
        font-size: 1.2rem;
        font-weight: 800;
        line-height: 1.35;
        margin-top: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# 기본 함수
# =========================================================

def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(value, max_value))


def calculate_scattering_distance(height, wind_speed):
    return 15 * (1 - math.exp(-0.08 * height * (1 + 0.3 * wind_speed)))


def get_risk_grade(r):
    if r <= 0.30:
        return (
            "안전",
            "기본 안전수칙 준수<br>"
            "작업 전 주변 가연물 확인",
            "#2ecc71"
        )
    elif r <= 0.80:
        return (
            "주의",
            "주변 가연물 정리<br>"
            "소화기 배치<br>"
            "화기 작업 조건 확인",
            "#f1c40f"
        )
    else:
        return (
            "위험",
            "근로자 개인 소화 키트 지참<br>"
            "화기 작업 작업자 1인당 화재감시자 1명씩 배치 준수",
            "#e74c3c"
        )


# =========================================================
# API 설정
# =========================================================

AUTH_KEY = "Gme6uZvRRZ6nurmb0ZWelQ"

# 배포 시에는 아래처럼 변경하세요.
# AUTH_KEY = st.secrets["AUTH_KEY"]

NX = 59
NY = 127

KST = timezone(timedelta(hours=9))

NCST_URL = (
    "https://apihub.kma.go.kr/api/typ02/openApi/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)

FCST_URL = (
    "https://apihub.kma.go.kr/api/typ02/openApi/"
    "VilageFcstInfoService_2.0/getUltraSrtFcst"
)


def get_now_kst():
    return datetime.now(KST)


def get_ncst_base_datetime():
    now = get_now_kst()

    if now.minute < 10:
        base = now - timedelta(hours=1)
    else:
        base = now

    return base.strftime("%Y%m%d"), base.strftime("%H00")


def get_fcst_base_datetime():
    now = get_now_kst()

    if now.minute < 45:
        base = now - timedelta(hours=1)
    else:
        base = now

    return base.strftime("%Y%m%d"), base.strftime("%H30")


def get_with_retry(url, params, timeout=30, retries=3, sleep_seconds=1):
    last_error = None

    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(sleep_seconds)
            else:
                raise
        except requests.exceptions.RequestException:
            raise

    if last_error:
        raise last_error


def fetch_ultra_srt_ncst(nx, ny, base_date, base_time, auth_key):
    params = {
        "authKey": auth_key,
        "numOfRows": "1000",
        "pageNo": "1",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    response = get_with_retry(
        NCST_URL,
        params=params,
        timeout=30,
        retries=3,
        sleep_seconds=1
    )

    data = response.json()

    if "response" not in data:
        raise RuntimeError(f"실황 응답 형식 오류: {data}")

    header = data["response"].get("header", {})
    result_code = str(header.get("resultCode", ""))
    result_msg = header.get("resultMsg", "")

    if result_code not in ("0", "00"):
        raise RuntimeError(f"실황 API 오류: {result_code} / {result_msg}")

    items = data["response"].get("body", {}).get("items", {}).get("item", [])

    if not items:
        raise RuntimeError("실황 데이터가 없습니다.")

    return items


def fetch_ultra_srt_fcst(nx, ny, base_date, base_time, auth_key):
    params = {
        "authKey": auth_key,
        "numOfRows": "1000",
        "pageNo": "1",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    response = get_with_retry(
        FCST_URL,
        params=params,
        timeout=30,
        retries=3,
        sleep_seconds=1
    )

    data = response.json()

    if "response" not in data:
        raise RuntimeError(f"예보 응답 형식 오류: {data}")

    header = data["response"].get("header", {})
    result_code = str(header.get("resultCode", ""))
    result_msg = header.get("resultMsg", "")

    if result_code not in ("0", "00"):
        raise RuntimeError(f"예보 API 오류: {result_code} / {result_msg}")

    items = data["response"].get("body", {}).get("items", {}).get("item", [])

    if not items:
        raise RuntimeError("예보 데이터가 없습니다.")

    return items


def parse_kma_weather(items):
    temperature = None
    humidity = None
    wind_speed = None

    for item in items:
        category = item.get("category")
        raw_value = item.get("obsrValue")

        if raw_value is None:
            continue

        try:
            value = float(raw_value)
        except Exception:
            continue

        if category == "T1H":
            temperature = value
        elif category == "REH":
            humidity = value
        elif category == "WSD":
            wind_speed = value

    return temperature, humidity, wind_speed


def parse_fcst_weather(items):
    grouped = {}

    for item in items:
        fcst_date = item.get("fcstDate")
        fcst_time = item.get("fcstTime")
        category = item.get("category")
        fcst_value = item.get("fcstValue")

        if not fcst_date or not fcst_time or not category:
            continue

        key = f"{fcst_date}{fcst_time}"

        if key not in grouped:
            grouped[key] = {}

        grouped[key][category] = fcst_value

    if not grouped:
        return None, None, None

    candidate_keys = sorted(grouped.keys())
    selected_key = candidate_keys[0]

    data = grouped[selected_key]
    sky = data.get("SKY")
    pty = data.get("PTY")

    return selected_key, sky, pty


def sky_to_text(sky):
    sky_map = {
        "1": "맑음",
        "3": "구름많음",
        "4": "흐림",
    }

    return sky_map.get(str(sky), "알 수 없음")


def pty_to_text(pty):
    pty_map = {
        "0": "없음",
        "1": "비",
        "2": "비/눈",
        "3": "눈",
        "4": "소나기",
        "5": "빗방울",
        "6": "빗방울눈날림",
        "7": "눈날림",
    }

    return pty_map.get(str(pty), "알 수 없음")


def make_today_weather_text(sky, pty):
    if str(pty) != "0":
        return pty_to_text(pty)

    return sky_to_text(sky)


# =========================================================
# 장비 점수
# =========================================================

equipment_scores = {
    "용접절단기(토치)": 100.0,
    "히터/히팅봉/가열장치": 48.7,
    "모터/인쇄기/집진기": 36.2,
    "그라인더": 27.6,
    "콤프레셔": 15.5,
    "전동톱/절단기": 10.9,
    "펌프": 8.8,
    "사출성형기": 6.8,
    "열풍기": 6.7,
    "보일러": 5.9,
    "방직기계": 5.2,
    "가스버너": 5.0,
    "산업용 용광로/가마": 4.5,
    "주조/주형/단조장비": 4.2,
    "동력선반": 3.2,
    "도장기계(부스)": 3.2,
    "컨베이어 벨트": 2.4,
    "기타(직접입력)": None
}


# =========================================================
# 세션 상태
# =========================================================

if "temperature" not in st.session_state:
    st.session_state.temperature = 30.0

if "humidity" not in st.session_state:
    st.session_state.humidity = 40.0

if "wind_speed" not in st.session_state:
    st.session_state.wind_speed = 3.0

if "today_weather" not in st.session_state:
    st.session_state.today_weather = "정보 없음"

if "weather_locked" not in st.session_state:
    st.session_state.weather_locked = False


# =========================================================
# 사이드바 입력
# =========================================================

st.sidebar.header("입력 데이터")

equipment = st.sidebar.selectbox(
    "장비 선택",
    list(equipment_scores.keys())
)

if equipment == "기타(직접입력)":
    equipment_score = st.sidebar.number_input(
        "선택된 장비 위험점수",
        min_value=0.0,
        max_value=100.0,
        value=50.0,
        step=0.1
    )
else:
    equipment_score = equipment_scores[equipment]
    st.sidebar.number_input(
        "선택된 장비 위험점수",
        value=float(equipment_score),
        step=0.1,
        disabled=True
    )

use_kma_weather = st.sidebar.checkbox(
    "기상청 실시간 값 사용",
    value=st.session_state.weather_locked
)

if not use_kma_weather:
    st.session_state.weather_locked = False

if st.sidebar.button("기상청 값 불러오기", use_container_width=True):
    if not use_kma_weather:
        st.sidebar.warning("먼저 '기상청 실시간 값 사용'을 체크해 주세요.")
    else:
        try:
            ncst_base_date, ncst_base_time = get_ncst_base_datetime()
            fcst_base_date, fcst_base_time = get_fcst_base_datetime()

            ncst_items = fetch_ultra_srt_ncst(
                nx=NX,
                ny=NY,
                base_date=ncst_base_date,
                base_time=ncst_base_time,
                auth_key=AUTH_KEY
            )

            fcst_items = fetch_ultra_srt_fcst(
                nx=NX,
                ny=NY,
                base_date=fcst_base_date,
                base_time=fcst_base_time,
                auth_key=AUTH_KEY
            )

            temp, hum, wind = parse_kma_weather(ncst_items)
            _, sky, pty = parse_fcst_weather(fcst_items)

            if temp is not None:
                st.session_state.temperature = temp

            if hum is not None:
                st.session_state.humidity = hum

            if wind is not None:
                st.session_state.wind_speed = wind

            st.session_state.today_weather = make_today_weather_text(sky, pty)
            st.session_state.weather_locked = True

            st.sidebar.success("기상청 값 불러오기 성공")

        except requests.exceptions.Timeout:
            st.sidebar.error("기상청 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.")
        except requests.exceptions.ConnectionError:
            st.sidebar.error("기상청 서버 연결이 불안정합니다. 잠시 후 다시 시도해 주세요.")
        except requests.exceptions.RequestException as e:
            st.sidebar.error(f"기상청 값 조회 실패: {e}")
        except Exception as e:
            st.sidebar.error(f"기상청 값 조회 실패: {e}")

weather_input_disabled = st.session_state.weather_locked and use_kma_weather

temperature = st.sidebar.number_input(
    "기온(℃)",
    min_value=-30.0,
    max_value=60.0,
    value=float(st.session_state.temperature),
    step=0.1,
    disabled=weather_input_disabled
)

humidity = st.sidebar.number_input(
    "상대습도(%)",
    min_value=0.0,
    max_value=100.0,
    value=float(st.session_state.humidity),
    step=0.1,
    disabled=weather_input_disabled
)

wind_speed = st.sidebar.number_input(
    "풍속 V(m/s)",
    min_value=0.0,
    max_value=30.0,
    value=float(st.session_state.wind_speed),
    step=0.1,
    disabled=weather_input_disabled
)

work_height = st.sidebar.number_input(
    "작업 높이 H(m)",
    min_value=0.1,
    max_value=21.0,
    value=5.0,
    step=0.1,
    help=(
        "한 층의 높이는 대략 2.3~2.5m이며, 작업 층수에 약 2.5를 곱한 높이로 "
        "생각해주시기 바랍니다. 지하층 작업의 경우 바닥면은 50cm, "
        "천장면에서의 작업의 경우 2m로 설정해주시기 바랍니다."
    )
)

if not weather_input_disabled:
    st.session_state.temperature = temperature
    st.session_state.humidity = humidity
    st.session_state.wind_speed = wind_speed

distance = calculate_scattering_distance(work_height, wind_speed)

STRIDE_LENGTH_M = 0.6
distance_steps = math.ceil(distance / STRIDE_LENGTH_M)

st.sidebar.markdown(
    f"""
    <div class="small-info-box">
        <div class="small-info-title">비산거리 / 보폭 기준 확인거리</div>
        <div class="small-info-main">D = {distance:.2f}m</div>
        <div class="small-info-sub">약 {distance_steps}보 이내 확인</div>
    </div>
    """,
    unsafe_allow_html=True
)

combustible_in_distance = st.sidebar.selectbox(
    "비산거리 내 가연물 존재 여부",
    ["없음", "있음"]
)

st.sidebar.caption(
    f"작업 위치 기준 약 {distance_steps}보 이내에 가연물이 있는지 확인하세요."
)


# =========================================================
# 계산
# =========================================================

E = equipment_score / 100.0
Dr = clamp(distance / 15.0)
RHr = clamp(1.1 - 0.01 * humidity)
Tr = clamp(temperature / 40.0)
W = clamp(2.9393 * Dr * RHr * Tr)

if combustible_in_distance == "있음":
    M_adj = clamp(0.75 + 0.25 * Dr)
    R = E * W * M_adj
else:
    M_adj = clamp(0.20 + 0.10 * Dr)
    R = E * W * M_adj

grade, action, grade_color = get_risk_grade(R)


# =========================================================
# 본문
# =========================================================

st.title("건설현장 화재위험도 대시보드")

st.markdown(
    "장비 위험도(E), 기상 위험도(W), 비산거리 내 가연물 존재 여부를 기반으로 "
    "최종 화재위험도를 계산합니다. "
    "비산거리(D)는 작업높이(H)와 풍속(V)으로 자동 계산됩니다."
)

st.subheader(f"오늘의 날씨: {st.session_state.today_weather}")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("최종 위험도", f"{R * 100:.1f}%")

with col2:
    st.metric("위험등급", grade)

with col3:
    st.metric("계산 비산거리 D", f"{distance:.2f} m")

with col4:
    st.metric("보폭 기준 확인거리", f"약 {distance_steps}보")

with col5:
    st.metric("상대습도 보정값 RHr", f"{RHr:.2f}")

st.subheader("보폭 기준 가연물 확인 범위")

st.markdown(
    f"""
    <div class="stride-box">
    계산된 비산거리: {distance:.2f}m<br>
    성인 남성 평균 보폭 0.6m 기준 확인거리: 약 {distance_steps}보<br>
    작업 위치 기준 약 {distance_steps}보 이내에 가연물이 있는지 확인하세요.
    </div>
    """,
    unsafe_allow_html=True
)

left, right = st.columns([1.2, 1])

with left:
    st.subheader("화재위험도 게이지")

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=R * 100,
        title={"text": "화재위험도(%)"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": grade_color},
            "steps": [
                {"range": [0, 30], "color": "#d5f5e3"},
                {"range": [30, 80], "color": "#fcf3cf"},
                {"range": [80, 100], "color": "#f5b7b1"},
            ],
        }
    ))

    fig_gauge.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=50, b=10)
    )

    st.plotly_chart(fig_gauge, use_container_width=True)

with right:
    st.subheader("권고조치")

    st.markdown(
        f"""
        <div class="recommend-box" style="background-color:{grade_color};">
        현재 등급: {grade}<br><br>
        {action}
        </div>
        """,
        unsafe_allow_html=True
    )


with st.expander("세부 계산값 보기"):
    result_df = pd.DataFrame({
        "항목": [
            "장비",
            "장비점수",
            "E",
            "기온",
            "상대습도",
            "풍속 V",
            "작업높이 H",
            "계산 비산거리 D",
            "보폭 기준 확인거리",
            "Dr",
            "RHr",
            "Tr",
            "W",
            "비산거리 내 가연물 존재 여부",
            "M_adj",
            "R",
            "위험등급",
            "오늘의 날씨"
        ],
        "값": [
            equipment,
            round(equipment_score, 3),
            round(E, 3),
            f"{temperature:.1f}℃",
            f"{humidity:.1f}%",
            f"{wind_speed:.1f}m/s",
            f"{work_height:.1f}m",
            f"{distance:.2f}m",
            f"약 {distance_steps}보",
            round(Dr, 3),
            round(RHr, 3),
            round(Tr, 3),
            round(W, 3),
            combustible_in_distance,
            round(M_adj, 3),
            round(R, 3),
            grade,
            st.session_state.today_weather
        ]
    })

    st.dataframe(result_df, use_container_width=True, hide_index=True)
