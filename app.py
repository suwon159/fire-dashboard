import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import math
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="건설현장 화재위험도 대시보드", layout="wide")


def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(value, max_value))


def calculate_scattering_distance(height, wind_speed):
    D = 15 * (1 - math.exp(-0.08 * height * (1 + 0.3 * wind_speed)))
    return D


def get_risk_grade(r):
    if r <= 0.20:
        return "안전", "작업 가능, 기본 안전수칙 준수", "#2ecc71"
    elif r <= 0.40:
        return "주의", "주변 가연물 정리 및 기본 소화기 배치", "#f1c40f"
    elif r <= 0.60:
        return "경계", "화기감시자 배치 및 소화기 추가 배치 권고", "#f39c12"
    elif r <= 0.80:
        return "위험", "비산방지포 설치 및 작업허가 재확인 필요", "#e74c3c"
    else:
        return "매우위험", "작업 중지 검토 및 관리자 승인 필요", "#8e0000"


# -----------------------------
# 기상청 API Hub 설정
# -----------------------------
AUTH_KEY = "Gme6uZvRRZ6nurmb0ZWelQ"

# 구로디지털단지 / 현대건설기술교육원 적용용
NX = 100
NY = 80


def get_base_datetime():
    """
    초단기실황은 매시각 10분 이후 현재 시각 자료 호출 가능
    예:
    14:03 -> 13:00 사용
    14:10 -> 14:00 사용
    14:35 -> 14:00 사용
    """
    now = datetime.now()

    if now.minute < 10:
        base = now - timedelta(hours=1)
    else:
        base = now

    base_date = base.strftime("%Y%m%d")
    base_time = base.strftime("%H00")
    return base_date, base_time


def fetch_kma_weather(nx, ny, base_date, base_time, auth_key):
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

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    # 디버깅용: 응답 형식 자체가 다른 경우
    if "response" not in data:
        raise RuntimeError(f"응답 형식 오류: {data}")

    header = data["response"].get("header", {})
    result_code = str(header.get("resultCode", ""))
    result_msg = header.get("resultMsg", "")

    # 가이드상 정상 코드는 0 또는 00 형태로 올 수 있음
    if result_code not in ("0", "00"):
        raise RuntimeError(f"기상청 API 오류: {result_code} / {result_msg}")

    body = data["response"].get("body", {})
    items = body.get("items", {}).get("item", [])

    if not items:
        raise RuntimeError("응답에 실황 데이터가 없습니다.")

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

# 지금 실행 중인 파일이 맞는지 확인용
st.caption(f"현재 AUTH_KEY = {AUTH_KEY}")


# -----------------------------
# session_state 초기화
# -----------------------------
if "temperature" not in st.session_state:
    st.session_state.temperature = 30.0

if "humidity" not in st.session_state:
    st.session_state.humidity = 40.0

if "wind_speed" not in st.session_state:
    st.session_state.wind_speed = 3.0

if "weather_debug" not in st.session_state:
    st.session_state.weather_debug = ""

if "last_base_date" not in st.session_state:
    st.session_state.last_base_date = ""

if "last_base_time" not in st.session_state:
    st.session_state.last_base_time = ""


# -----------------------------
# 입력 영역
# -----------------------------
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


# -----------------------------
# 기상청 실시간 값 가져오기
# -----------------------------
use_kma_weather = st.sidebar.checkbox("기상청 실시간 값 사용", value=False)

if use_kma_weather:
    if st.sidebar.button("기상청 값 불러오기"):
        try:
            base_date, base_time = get_base_datetime()
            st.session_state.last_base_date = base_date
            st.session_state.last_base_time = base_time

            items = fetch_kma_weather(
                nx=NX,
                ny=NY,
                base_date=base_date,
                base_time=base_time,
                auth_key=AUTH_KEY
            )

            temp, hum, wind = parse_kma_weather(items)
            st.session_state.weather_debug = str(items)

            if temp is not None:
                st.session_state.temperature = temp
            if hum is not None:
                st.session_state.humidity = hum
            if wind is not None:
                st.session_state.wind_speed = wind

            st.sidebar.success(f"기상청 값 불러오기 성공 ({base_date} {base_time})")

        except Exception as e:
            st.sidebar.error(f"기상청 값 조회 실패: {e}")

if st.session_state.last_base_date and st.session_state.last_base_time:
    st.sidebar.caption(
        f"최근 조회 기준시각: {st.session_state.last_base_date} {st.session_state.last_base_time}"
    )

temperature = st.sidebar.number_input(
    "기온(℃)",
    min_value=-30.0,
    max_value=60.0,
    value=float(st.session_state.temperature),
    step=0.1
)

humidity = st.sidebar.number_input(
    "습도(%)",
    min_value=0.0,
    max_value=100.0,
    value=float(st.session_state.humidity),
    step=0.1
)

work_height = st.sidebar.number_input(
    "작업 높이 H(m)",
    min_value=0.1,
    max_value=21.0,
    value=5.0,
    step=0.1
)

wind_speed = st.sidebar.number_input(
    "풍속 V(m/s)",
    min_value=0.0,
    max_value=30.0,
    value=float(st.session_state.wind_speed),
    step=0.1
)

distance = calculate_scattering_distance(work_height, wind_speed)


# -----------------------------
# 보폭 계산
# -----------------------------
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


# -----------------------------
# 가연물 입력
# -----------------------------
st.sidebar.subheader("비산거리 내 가연물 존재 여부")

combustible_in_distance = st.sidebar.selectbox(
    f"계산된 비산거리 {distance:.2f}m, 약 {distance_steps}보 이내에 가연물이 있습니까?",
    ["없음", "있음"]
)


# -----------------------------
# 계산
# -----------------------------
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


# -----------------------------
# KPI
# -----------------------------
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
    st.metric("습도 보정값 RHr", f"{RHr:.2f}")


# -----------------------------
# 보폭 기준 확인 안내
# -----------------------------
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


# -----------------------------
# 게이지
# -----------------------------
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
                {"range": [0, 20], "color": "#d5f5e3"},
                {"range": [20, 40], "color": "#fcf3cf"},
                {"range": [40, 60], "color": "#fdebd0"},
                {"range": [60, 80], "color": "#f5b7b1"},
                {"range": [80, 100], "color": "#d98880"},
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


# -----------------------------
# 비교 차트
# -----------------------------
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


# -----------------------------
# 현재 조건에서 가연물 유무 비교
# -----------------------------
st.subheader("현재 조건에서 가연물 유무에 따른 위험도 비교")

M_with_combustible = clamp(0.75 + 0.25 * Dr)
R_with_combustible = E * W * M_with_combustible

M_without_combustible = clamp(0.20 + 0.10 * Dr)
R_without_combustible = E * W * M_without_combustible

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
    ]
})

fig_compare = px.bar(
    df_compare,
    x="조건",
    y="최종 위험도(%)",
    text="최종 위험도(%)"
)

fig_compare.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_compare.update_layout(yaxis_range=[0, 100])

st.plotly_chart(fig_compare, use_container_width=True)


# -----------------------------
# 높이별 위험도 비교 예시
# -----------------------------
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

    sample_results.append({
        "작업 높이(m)": h,
        "비산거리 D(m)": round(sample_distance, 2),
        "확인 필요 거리(보)": sample_steps,
        "Dr": round(sample_dr, 3),
        "W": round(sample_w, 3),
        "가연물 있음 M_adj": round(sample_m_with, 3),
        "가연물 있음 위험도(%)": round(sample_r_with * 100, 1),
        "가연물 없음 M_adj": round(sample_m_without, 3),
        "가연물 없음 위험도(%)": round(sample_r_without * 100, 1)
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


# -----------------------------
# 세부 계산값
# -----------------------------
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
        "R"
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
        round(R, 3)
    ]
})

st.dataframe(result_df, use_container_width=True, hide_index=True)


with st.expander("기상청 응답 디버깅 보기"):
    st.write(st.session_state.weather_debug)
