import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import math
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="건설현장 화재위험도 대시보드", layout="wide")


def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(value, max_value))


def calculate_scattering_distance(height, wind_speed):
    return 15 * (1 - math.exp(-0.08 * height * (1 + 0.3 * wind_speed)))


def get_risk_grade(r):
    if r <= 0.30:
        return "안전", "작업 가능, 기본 안전수칙을 준수하세요.", "#2ecc71"
    elif r <= 0.80:
        return "주의", "주변 가연물 정리, 소화기 배치, 화기 작업 조건을 확인하세요.", "#f1c40f"
    else:
        return "위험", "작업 전 관리자 확인, 화기감시자 배치, 가연물 제거 후 작업하세요.", "#e74c3c"


AUTH_KEY = "Gme6uZvRRZ6nurmb0ZWelQ"

NX = 59
NY = 127

KST = timezone(timedelta(hours=9))


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
    url = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst"
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

    response = get_with_retry(url, params=params, timeout=30, retries=3, sleep_seconds=1)
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
    url = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst"
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

    response = get_with_retry(url, params=params, timeout=30, retries=3, sleep_seconds=1)
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
    pty_text = pty_to_text(pty)
    if str(pty) != "0":
        return pty_text
    return sky_to_text(sky)


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


st.title("건설현장 화재위험도 대시보드")

st.markdown(
    "장비 위험도(E), 기상 위험도(W), 비산거리 내 가연물 존재 여부를 기반으로 "
    "최종 화재위험도를 계산합니다. "
    "비산거리(D)는 작업높이(H)와 풍속(V)으로 자동 계산됩니다."
)

if "temperature" not in st.session_state:
    st.session_state.temperature = 30.0

if "humidity" not in st.session_state:
    st.session_state.humidity = 40.0

if "wind_speed" not in st.session_state:
    st.session_state.wind_speed = 3.0

if "today_weather" not in st.session_state:
    st.session_state.today_weather = "정보 없음"

if "weather_debug" not in st.session_state:
    st.session_state.weather_debug = ""

if "fcst_debug" not in st.session_state:
    st.session_state.fcst_debug = ""

if "last_ncst_base" not in st.session_state:
    st.session_state.last_ncst_base = ""

if "last_fcst_base" not in st.session_state:
    st.session_state.last_fcst_base = ""

if "last_fcst_target" not in st.session_state:
    st.session_state.last_fcst_target = ""

if "weather_locked" not in st.session_state:
    st.session_state.weather_locked = False


st.sidebar.header("입력 데이터")

equipment = st.sidebar.selectbox("장비 선택", list(equipment_scores.keys()))

if equipment == "기타(직접입력)":
    equipment_score = st.sidebar.number_input(
        "기타 장비 위험점수",
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

use_kma_weather = st.sidebar.checkbox("기상청 실시간 값 사용", value=False)

if not use_kma_weather:
    st.session_state.weather_locked = False

if use_kma_weather:
    if st.sidebar.button("기상청 값 불러오기"):
        try:
            ncst_base_date, ncst_base_time = get_ncst_base_datetime()
            fcst_base_date, fcst_base_time = get_fcst_base_datetime()

            st.session_state.last_ncst_base = f"{ncst_base_date} {ncst_base_time}"
            st.session_state.last_fcst_base = f"{fcst_base_date} {fcst_base_time}"

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
            fcst_target, sky, pty = parse_fcst_weather(fcst_items)

            st.session_state.weather_debug = str(ncst_items)
            st.session_state.fcst_debug = str(fcst_items)

            if temp is not None:
                st.session_state.temperature = temp
            if hum is not None:
                st.session_state.humidity = hum
            if wind is not None:
                st.session_state.wind_speed = wind

            st.session_state.today_weather = make_today_weather_text(sky, pty)
            st.session_state.last_fcst_target = fcst_target if fcst_target else ""
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

if st.session_state.last_ncst_base:
    st.sidebar.caption(f"실황 기준시각: {st.session_state.last_ncst_base}")

if st.session_state.last_fcst_base:
    st.sidebar.caption(f"예보 발표시각: {st.session_state.last_fcst_base}")

if st.session_state.last_fcst_target:
    st.sidebar.caption(f"날씨 상태 적용시각: {st.session_state.last_fcst_target}")

st.subheader(f"오늘의 날씨: {st.session_state.today_weather}")

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
    help="❗ 한 층의 높이는 대략 2.3~2.5m이며, 작업 층수에 약 2.5를 곱한 높이로 생각해주시기 바랍니다. 지하층 작업의 경우 바닥면은 50cm, 천장면에서의 작업의 경우 2m로 설정해주시기 바랍니다."
)

distance = calculate_scattering_distance(work_height, wind_speed)

STRIDE_LENGTH_M = 0.6
distance_steps = math.ceil(distance / STRIDE_LENGTH_M)

st.sidebar.number_input(
    "계산된 비산거리 D(m)",
    value=float(distance),
    step=0.1,
    disabled=True
)

st.sidebar.number_input(
    "확인 필요 거리(보폭 기준)",
    value=int(distance_steps),
    step=1,
    disabled=True
)

st.sidebar.caption(
    f"성인 남성 평균 보폭 0.6m 기준으로 약 {distance_steps}보 이내를 확인하세요."
)

st.sidebar.subheader("비산거리 내 가연물 존재 여부")

combustible_in_distance = st.sidebar.selectbox(
    f"계산된 비산거리 {distance:.2f}m, 약 {distance_steps}보 이내에 가연물이 있습니까?",
    ["없음", "있음"]
)

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

stride_box = (
    '<div style="'
    'background-color:#34495e;'
    'padding:16px;'
    'border-radius:12px;'
    'color:white;'
    'font-size:18px;'
    'font-weight:bold;'
    'text-align:center;">'
    f'계산된 비산거리: {distance:.2f}m<br>'
    f'성인 남성 평균 보폭 0.6m 기준 확인거리: 약 {distance_steps}보<br>'
    f'작업 위치 기준 약 {distance_steps}보 이내에 가연물이 있는지 확인하세요.'
    '</div>'
)

st.markdown(stride_box, unsafe_allow_html=True)

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

    st.plotly_chart(fig_gauge, use_container_width=True)

with right:
    st.subheader("권고조치")

    action_box = (
        '<div style="'
        f'background-color:{grade_color};'
        'padding:20px;'
        'border-radius:12px;'
        'color:white;'
        'font-size:20px;'
        'font-weight:bold;'
        'text-align:center;">'
        f'현재 등급: {grade}<br><br>'
        f'{action}'
        '</div>'
    )

    st.markdown(action_box, unsafe_allow_html=True)

c1, c2 = st.columns(2)

with c1:
    st.subheader("E / W / M_adj 비교")

    df_factor = pd.DataFrame({
        "구분": [
            "장비 위험도(E)",
            "기상 위험도(W)",
            "가연물 보정위험도(M_adj)"
        ],
        "값": [E, W, M_adj]
    })

    fig_bar = px.bar(df_factor, x="구분", y="값", text="값")
    fig_bar.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig_bar.update_layout(yaxis_range=[0, 1])

    st.plotly_chart(fig_bar, use_container_width=True)

with c2:
    st.subheader("비산거리 내 가연물 존재 여부")

    df_combustible = pd.DataFrame({
        "구분": ["비산거리 내 가연물"],
        "상태": [combustible_in_distance],
        "M_adj": [M_adj]
    })

    fig_combustible = px.bar(
        df_combustible,
        x="구분",
        y="M_adj",
        text="상태"
    )

    fig_combustible.update_traces(textposition="outside")
    fig_combustible.update_layout(yaxis_range=[0, 1])

    st.plotly_chart(fig_combustible, use_container_width=True)

st.subheader("현재 조건에서 가연물 유무에 따른 위험도 비교")

M_with_combustible = clamp(0.75 + 0.25 * Dr)
R_with_combustible = E * W * M_with_combustible

M_without_combustible = clamp(0.20 + 0.10 * Dr)
R_without_combustible = E * W * M_without_combustible

grade_without, _, _ = get_risk_grade(R_without_combustible)
grade_with, _, _ = get_risk_grade(R_with_combustible)

df_compare = pd.DataFrame({
    "조건": [
        "비산거리 내 가연물 없음",
        "비산거리 내 가연물 있음"
    ],
    "M_adj": [
        round(M_without_combustible, 3),
        round(M_with_combustible, 3)
    ],
    "최종 위험도(%)": [
        round(R_without_combustible * 100, 1),
        round(R_with_combustible * 100, 1)
    ],
    "위험등급": [
        grade_without,
        grade_with
    ]
})

fig_compare = px.bar(
    df_compare,
    x="조건",
    y="최종 위험도(%)",
    text="위험등급"
)

fig_compare.update_traces(textposition="outside")
fig_compare.update_layout(yaxis_range=[0, 100])

st.plotly_chart(fig_compare, use_container_width=True)

st.subheader("작업 높이별 위험도 변화 예시")

sample_heights = [1, 3, 5, 10, 15, 21]
sample_results = []

for h in sample_heights:
    sample_distance = calculate_scattering_distance(h, wind_speed)
    sample_dr = clamp(sample_distance / 15.0)
    sample_steps = math.ceil(sample_distance / STRIDE_LENGTH_M)

    sample_w = clamp(2.9393 * sample_dr * RHr * Tr)

    sample_m_with = clamp(0.75 + 0.25 * sample_dr)
    sample_r_with = E * sample_w * sample_m_with

    sample_m_without = clamp(0.20 + 0.10 * sample_dr)
    sample_r_without = E * sample_w * sample_m_without

    sample_grade_with, _, _ = get_risk_grade(sample_r_with)
    sample_grade_without, _, _ = get_risk_grade(sample_r_without)

    sample_results.append({
        "작업 높이(m)": h,
        "비산거리 D(m)": round(sample_distance, 2),
        "확인 필요 거리(보)": sample_steps,
        "Dr": round(sample_dr, 3),
        "W": round(sample_w, 3),
        "가연물 있음 M_adj": round(sample_m_with, 3),
        "가연물 있음 위험도(%)": round(sample_r_with * 100, 1),
        "가연물 있음 등급": sample_grade_with,
        "가연물 없음 M_adj": round(sample_m_without, 3),
        "가연물 없음 위험도(%)": round(sample_r_without * 100, 1),
        "가연물 없음 등급": sample_grade_without
    })

df_height_compare = pd.DataFrame(sample_results)

st.dataframe(df_height_compare, use_container_width=True, hide_index=True)

fig_height = px.line(
    df_height_compare,
    x="작업 높이(m)",
    y="가연물 있음 위험도(%)",
    markers=True
)

fig_height.update_layout(yaxis_range=[0, 100])

st.plotly_chart(fig_height, use_container_width=True)

st.subheader("세부 계산값")

result_df = pd.DataFrame({
    "항목": [
        "장비점수",
        "E",
        "작업높이 H",
        "풍속 V",
        "계산 비산거리 D",
        "보폭 기준 확인거리",
        "Dr",
        "RHr",
        "Tr",
        "W",
        "비산거리 내 가연물 존재 여부",
        "M_adj(보정)",
        "R",
        "위험등급",
        "오늘의 날씨"
    ],
    "값": [
        round(equipment_score, 3),
        round(E, 3),
        round(work_height, 3),
        round(wind_speed, 3),
        round(distance, 3),
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
