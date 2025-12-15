import csv
import os
import time
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    WebDriverException,
)


# =========================
# Rotten Tomatoes TARGETS
# =========================
RT_TARGETS = [
    # ---------- 성공 ----------
    {
        "title_ko": "오징어 게임",
        "title_en": "Squid Game",
        "year": 2021,
        "rt_url": "https://www.rottentomatoes.com/tv/squid_game/s01/reviews?type=user",
    },
    {
        "title_ko": "더 글로리",
        "title_en": "The Glory",
        "year": 2022,
        "rt_url": "https://www.rottentomatoes.com/tv/the_glory/s01/reviews?type=user",
    },
    {
        "title_ko": "기생충",
        "title_en": "Parasite",
        "year": 2019,
        "rt_url": "https://www.rottentomatoes.com/m/parasite_2019/reviews?type=user",
    },

    # ---------- 호불호 ----------
    {
        "title_ko": "경성 크리처",
        "title_en": "Gyeongseong Creature",
        "year": 2023,
        "rt_url": "https://www.rottentomatoes.com/tv/gyeongseong_creature/s01/reviews?type=user",
    },
    {
        "title_ko": "킹더랜드",
        "title_en": "King the Land",
        "year": 2023,
        "rt_url": "https://www.rottentomatoes.com/tv/king_the_land/s01/reviews?type=user",
    },
    {
        "title_ko": "지금 우리 학교는 시즌 1",
        "title_en": "All of Us Are Dead Season 1",
        "year": 2022,
        "rt_url": "https://www.rottentomatoes.com/tv/all_of_us_are_dead/s01/reviews?type=user",
    },

    # ---------- 실패 ----------
    {
        "title_ko": "택배기사",
        "title_en": "Black Knight",
        "year": 2023,
        "rt_url": "https://www.rottentomatoes.com/tv/black_knight/s01/reviews?type=user",
    },
    {
        "title_ko": "야차",
        "title_en": "Yaksha: Ruthless Operations",
        "year": 2022,
        "rt_url": "https://www.rottentomatoes.com/m/yaksha_ruthless_operations/reviews?type=user",
    },
    {
        "title_ko": "카터",
        "title_en": "Carter",
        "year": 2022,
        "rt_url": "https://www.rottentomatoes.com/m/carter_2022/reviews?type=user",
    },
]




OUTPUT_CSV = "rt_reviews.csv"


# =========================================================
# 2. 드라이버 생성
# =========================================================

def create_driver(headless: bool = False) -> webdriver.Chrome:
    chrome_options = webdriver.ChromeOptions()

    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--start-maximized")

    chrome_options.add_experimental_option(
        "excludeSwitches", ["enable-automation"]
    )
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if headless:
        chrome_options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_window_size(1280, 900)
    driver.implicitly_wait(3)
    return driver


# =========================================================
# 3. 유틸 함수
# =========================================================

def _slugify(text: str) -> str:
    return (
        "".join(c.lower() if c.isalnum() else "_" for c in text)
        .strip("_")
        .replace("__", "_")
    )


def _save_debug_html(html: str, path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        print(f"[DEBUG] HTML 저장 실패 ({path}): {e}")


def close_rt_cookie_banner(driver, wait_seconds: int = 5) -> None:
    """
    하단 쿠키/약관 배너의 'Continue' 버튼을 눌러서 없앤다.
    없으면 그냥 패스.
    """
    try:
        wait = WebDriverWait(driver, wait_seconds)
        btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(.), 'Continue')]",
                )
            )
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(1.0)
        print("[RT] 쿠키/약관 배너 'Continue' 클릭 완료")
    except TimeoutException:
        print("[RT] 쿠키/약관 배너 없음 (또는 이미 처리됨)")
    except Exception as e:
        print(f"[RT] 쿠키/약관 배너 클릭 중 예외 발생: {e}")


# =========================================================
# 4. 리뷰 카드 파싱
# =========================================================

def _parse_rt_review_card(card) -> Dict[str, str]:
    """단일 review-card에서 rating/date/review 텍스트 추출."""
    # 날짜
    try:
        date_text = card.find_element(
            By.CSS_SELECTOR, "span[slot='timestamp']"
        ).text.strip()
    except NoSuchElementException:
        date_text = ""

    # 리뷰 본문
    try:
        review_text = card.find_element(
            By.CSS_SELECTOR,
            "drawer-more[slot='review'] span[slot='content']",
        ).text.strip()
    except NoSuchElementException:
        review_text = ""

    # 평점 (percentage/score/sentiment)
    rating = ""
    score_el = None
    try:
        score_el = card.find_element(
            By.CSS_SELECTOR, "[slot='rating'] score-icon-audience"
        )
    except NoSuchElementException:
        try:
            score_el = card.find_element(
                By.CSS_SELECTOR, "[slot='rating'] score-icon-critics"
            )
        except NoSuchElementException:
            score_el = None

    if score_el is not None:
        rating = (
            (score_el.get_attribute("percentage") or "")
            or (score_el.get_attribute("score") or "")
            or (score_el.get_attribute("sentiment") or "")
        ).strip()

    return {
        "rating": rating,
        "date": date_text,
        "review": review_text,
    }


# =========================================================
# 5. 한 타이틀 크롤링
# =========================================================

def crawl_rt_audience_reviews_for_target(
    driver: webdriver.Chrome,
    target: Dict,
    max_pages: int = 30,
    wait_seconds: int = 10,
) -> List[Dict[str, str]]:
    """
    한 타이틀에 대해 Rotten Tomatoes Audience Reviews를 가능한 많이 수집.
    """
    title_ko = target["title_ko"]
    title_en = target["title_en"]
    year = target["year"]
    rt_url = target["rt_url"]

    print(f"[RT] '{title_en}' Audience Reviews 수집 시작 → {rt_url}")
    os.makedirs("debug", exist_ok=True)
    safe_key = _slugify(title_en)

    rows: List[Dict[str, str]] = []
    seen_keys = set()  # (date, review[:80]) 기준 중복 제거

    driver.get(rt_url)
    close_rt_cookie_banner(driver, wait_seconds=5)

    wait = WebDriverWait(driver, wait_seconds)

    # 리뷰 섹션 대기
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "section[data-qa='section:reviews']")
            )
        )
    except TimeoutException:
        print(f"[RT] {title_en} – 리뷰 섹션을 찾지 못함.")
        _save_debug_html(
            driver.page_source,
            os.path.join("debug", f"rt_{safe_key}_no_section.html"),
        )
        return rows

    # All Audience 탭 클릭 (있으면)
    try:
        all_aud_btn = driver.find_element(
            By.CSS_SELECTOR, "rt-button[data-qa='all-audience']"
        )
        driver.execute_script("arguments[0].click();", all_aud_btn)
        time.sleep(1.5)
    except NoSuchElementException:
        pass
    except WebDriverException:
        pass

    # 카드 컨테이너 대기
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.reviews-cards[data-pagemediareviewsmanager='cards']",
                )
            )
        )
    except TimeoutException:
        print(f"[RT] {title_en} – 리뷰 카드 컨테이너를 찾지 못함.")
        _save_debug_html(
            driver.page_source,
            os.path.join("debug", f"rt_{safe_key}_no_cards.html"),
        )
        return rows

    _save_debug_html(
        driver.page_source,
        os.path.join("debug", f"rt_{safe_key}_page0.html"),
    )
    print(f"[DEBUG] 초기 HTML 저장됨 → debug/rt_{safe_key}_page0.html")

    page_idx = 1
    last_dom_count = 0
    stagnant_rounds = 0

    while True:
        time.sleep(1.0)

        cards = driver.find_elements(
            By.CSS_SELECTOR,
            "div.reviews-cards[data-pagemediareviewsmanager='cards'] review-card",
        )
        cur_dom_count = len(cards)
        print(
            f"[RT] {title_en} – page {page_idx}: DOM 상 리뷰 카드 수: {cur_dom_count}"
        )

        new_rows_this_round = 0
        for card in cards:
            parsed = _parse_rt_review_card(card)
            if not parsed["review"]:
                continue

            key = (parsed["date"], parsed["review"][:80])
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows.append(
                {
                    "site": "RT",
                    "title_ko": title_ko,
                    "title_en": title_en,
                    "year": str(year),
                    "rating": parsed["rating"],
                    "date": parsed["date"],
                    "review": parsed["review"],
                }
            )
            new_rows_this_round += 1

        print(
            f"[RT] {title_en} – 이번 라운드 신규 {new_rows_this_round}개, 누적 {len(rows)}개"
        )

        # DOM 변화 체크
        if cur_dom_count == last_dom_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
        last_dom_count = cur_dom_count

        if stagnant_rounds >= 2:
            print(f"[RT] {title_en} – 2 라운드 연속 새 카드 없음, 종료.")
            break

        if page_idx >= max_pages:
            print(f"[RT] {title_en} – max_pages({max_pages}) 도달, 종료.")
            break

        # Load More 버튼 클릭
        try:
            load_more_btn = driver.find_element(
                By.CSS_SELECTOR,
                "rt-button[data-pagemediareviewsmanager='loadMoreBtn']",
            )
            is_hidden = load_more_btn.get_attribute("hidden") is not None
            if is_hidden:
                print(f"[RT] {title_en} – Load More 버튼 hidden, 종료.")
                break

            driver.execute_script("arguments[0].click();", load_more_btn)
            print(f"[RT] {title_en} – Load More 클릭 {page_idx}회")
            page_idx += 1
            time.sleep(2.0)
        except NoSuchElementException:
            print(f"[RT] {title_en} – Load More 버튼 없음, 종료.")
            break
        except ElementClickInterceptedException:
            print(f"[RT] {title_en} – Load More 클릭 실패, 종료.")
            break

    _save_debug_html(
        driver.page_source,
        os.path.join("debug", f"rt_{safe_key}_last.html"),
    )
    print(f"[DEBUG] 마지막 HTML 저장됨 → debug/rt_{safe_key}_last.html")
    print(f"[RT] {title_en} – 최종 {len(rows)}개 수집 후 종료")

    return rows


# =========================================================
# 6. CSV 저장
# =========================================================

def save_to_csv(path: str, rows: List[Dict[str, str]]) -> None:
    if not rows:
        print("[WARN] 저장할 데이터가 없습니다.")
        return

    fieldnames = ["site", "title_ko", "title_en", "year", "rating", "date", "review"]
    file_exists = os.path.exists(path)

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"[SAVE] {path} (이번에 {len(rows)}개 추가)")


# =========================================================
# 7. 엔트리 포인트
# =========================================================

def main() -> None:
    MAX_PAGES_PER_TITLE = 50

    driver = create_driver(headless=False)

    try:
        total = 0
        for tgt in RT_TARGETS:
            print(
                f"\n[RT-CRAWL] {tgt['title_ko']} / {tgt['title_en']} ({tgt['year']})"
            )
            rows = crawl_rt_audience_reviews_for_target(
                driver,
                tgt,
                max_pages=MAX_PAGES_PER_TITLE,
            )
            save_to_csv(OUTPUT_CSV, rows)
            total += len(rows)

        print(f"\n[RT-CRAWL] 전체 타이틀 합산 {total}개 수집 완료")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
