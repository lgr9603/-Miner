import csv
import os
import time
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


# =========================================================
# 1. 크롬 드라이버 생성
# =========================================================

def create_driver(headless: bool = False) -> webdriver.Chrome:
    chrome_options = Options()

    if headless:
        chrome_options.add_argument("--headless=new")

    # 안정성 옵션
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=chrome_options)
    driver.implicitly_wait(3)
    return driver


# =========================================================
# 2. 단일 리뷰 카드 파싱
# =========================================================

def parse_review_element(
    el, title_ko: str, title_en: str, year: int
) -> Optional[Dict[str, str]]:
    """
    IMDb 리뷰 카드 하나에서 rating / date / review 텍스트를 추출.
    (새 DOM 기준)
    """
    try:
        # ---- rating ----
        rating = ""
        try:
            rating_el = el.find_element(
                By.CSS_SELECTOR,
                "span.ipc-rating-star--rating"
            )
            txt = rating_el.text.strip()
            if txt:
                # 예: "9" 또는 "9/10"
                rating = txt.split("/")[0].strip()
        except Exception:
            pass

        # ---- review text ----
        review_text = ""
        try:
            text_el = el.find_element(
                By.CSS_SELECTOR,
                "div[data-testid='review-overflow'] "
                "div.ipc-html-content-inner-div"
            )
            txt = text_el.text.strip()
            if txt:
                review_text = txt.replace("\n", " ").strip()
        except Exception:
            pass

        # ---- date ----
        # 최근 IMDb 레이아웃에서는 날짜가 별도 span으로 안 나와서 일단 빈 값
        date_text = ""

        if not review_text:
            return None

        return {
            "title_ko": title_ko,
            "title_en": title_en,
            "year": str(year),
            "rating": rating,
            "date": date_text,
            "review": review_text,
        }

    except Exception:
        return None


# =========================================================
# 3. 특정 작품(ttid) 리뷰 크롤링 (25 more 버튼 + 증분 파싱)
# =========================================================

def crawl_imdb_reviews_for_title(
    driver: webdriver.Chrome,
    title_ko: str,
    title_en: str,
    year: int,
    ttid: str,
    max_reviews: int = 1000,
    max_clicks: int = 100,
    click_timeout: float = 6.0,  # 호출부와 시그니처 맞추기용 (내부에선 안 씀)
) -> List[Dict[str, str]]:
    """
    /title/{ttid}/reviews 페이지에서:

      1) 초기로 로드된 리뷰 25개 파싱
      2) 하단 "25 more" 버튼 반복 클릭
      3) 클릭될 때마다 새로 늘어난 카드만 파싱

    이런 식으로 최대 max_reviews까지 수집.
    """
    url = f"https://www.imdb.com/title/{ttid}/reviews"
    print(f"[IMDB] '{title_en}' 리뷰 수집 시작 (ttid={ttid})")
    driver.get(url)

    wait = WebDriverWait(driver, 10)

    # ---- 0) 초기 리뷰 카드 DOM 등장까지 대기 ----
    try:
        wait.until(
            lambda d: len(
                d.find_elements(
                    By.CSS_SELECTOR,
                    "div[data-testid='review-card-parent']"
                )
            ) > 0
        )
    except TimeoutException:
        # 이 타이틀은 새 리뷰 카드 DOM이 없을 수 있음 (리뷰 없음 / 다른 레이아웃 등)
        os.makedirs("debug", exist_ok=True)
        debug_path = os.path.join(
            "debug", f"imdb_reviews_{ttid}_no_review_cards.html"
        )
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(
            f"[IMDB] {title_en} – 리뷰 카드 DOM을 찾지 못함. "
            f"HTML 저장 → {debug_path}. 이 타이틀은 스킵합니다."
        )
        return []

    # ---- 디버그용 초기 HTML 저장 ----
    os.makedirs("debug", exist_ok=True)
    debug_path = os.path.join("debug", f"imdb_reviews_{ttid}_page0.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[DEBUG] 초기 HTML 저장됨 → {debug_path}")

    collected: List[Dict[str, str]] = []
    seen_ids = set()

    # ---- 1) 처음 로드된 리뷰들 파싱 ----
    review_elements = driver.find_elements(
        By.CSS_SELECTOR,
        "div[data-testid='review-card-parent']"
    )
    prev_count = len(review_elements)
    print(f"[IMDB] {title_en} – 초기 리뷰 카드 수: {prev_count}")

    for idx, el in enumerate(review_elements):
        rid = None
        try:
            link = el.find_element(
                By.CSS_SELECTOR,
                "a[href*='/review/']"
            )
            href = link.get_attribute("href") or ""
            if href:
                rid = href
        except Exception:
            pass
        if not rid:
            rid = f"idx-0-{idx}"

        if rid in seen_ids:
            continue

        parsed = parse_review_element(el, title_ko, title_en, year)
        if not parsed:
            continue

        seen_ids.add(rid)
        collected.append(parsed)

    print(f"[IMDB] {title_en} – 초기 수집: {len(collected)}개")

    if len(collected) >= max_reviews:
        print(f"[IMDB] {title_en} – max_reviews({max_reviews}) 도달, 종료")
        return collected

    # ---- 2) '25 more' 버튼 클릭 반복 ----
    click_count = 0

    while click_count < max_clicks and len(collected) < max_reviews:
        # 맨 아래로 스크롤해서 버튼 보이게
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )
        time.sleep(0.5)

        # "25 more" 버튼 찾기
        try:
            more_btn = driver.find_element(
                By.XPATH,
                "//button[.//span[contains(@class,'ipc-see-more__text') and "
                "contains(normalize-space(.), '25 more')]]"
            )
        except Exception:
            print(
                f"[IMDB] {title_en} – '25 more' 버튼 없음, 추가 리뷰 없음, 종료"
            )
            break

        # 클릭
        try:
            driver.execute_script("arguments[0].click();", more_btn)
            click_count += 1
            print(
                f"[IMDB] {title_en} – '25 more' 버튼 클릭 {click_count}회"
            )
        except Exception as e:
            print(
                f"[IMDB] {title_en} – '25 more' 클릭 중 예외 발생, 종료: {e}"
            )
            break

        # 새 리뷰 카드가 로드될 때까지 개수 증가 기준으로 대기
        def _new_reviews_loaded(d):
            elems = d.find_elements(
                By.CSS_SELECTOR,
                "div[data-testid='review-card-parent']"
            )
            return len(elems) > prev_count

        try:
            wait.until(_new_reviews_loaded)
        except TimeoutException:
            print(
                f"[IMDB] {title_en} – 클릭 후 새 리뷰 카드가 안 늘어남, 종료"
            )
            break

        # 늘어난 만큼만 새로 파싱
        review_elements = driver.find_elements(
            By.CSS_SELECTOR,
            "div[data-testid='review-card-parent']"
        )
        new_count = len(review_elements)
        print(
            f"[IMDB] {title_en} – 클릭 후 리뷰 카드 수: {new_count}"
        )

        new_elems = review_elements[prev_count:new_count]
        prev_count = new_count

        for idx, el in enumerate(new_elems):
            rid = None
            try:
                link = el.find_element(
                    By.CSS_SELECTOR,
                    "a[href*='/review/']"
                )
                href = link.get_attribute("href") or ""
                if href:
                    rid = href
            except Exception:
                pass
            if not rid:
                rid = f"idx-{click_count}-{idx}"

            if rid in seen_ids:
                continue

            parsed = parse_review_element(el, title_ko, title_en, year)
            if not parsed:
                continue

            seen_ids.add(rid)
            collected.append(parsed)

            if len(collected) % 50 == 0:
                print(
                    f"[IMDB] {title_en} – 현재까지 {len(collected)}개 수집"
                )

            if len(collected) >= max_reviews:
                print(
                    f"[IMDB] {title_en} – max_reviews({max_reviews}) 도달, 종료"
                )
                debug_path_last = os.path.join(
                    "debug", f"imdb_reviews_{ttid}_last.html"
                )
                with open(debug_path_last, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"[DEBUG] 마지막 HTML 저장됨 → {debug_path_last}")
                return collected

    print(
        f"[IMDB] {title_en} – 총 {len(collected)}개 수집 후 종료"
    )

    debug_path_last = os.path.join("debug", f"imdb_reviews_{ttid}_last.html")
    with open(debug_path_last, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[DEBUG] 마지막 HTML 저장됨 → {debug_path_last}")

    return collected


# =========================================================
# 4. CSV 저장
# =========================================================

def save_to_csv(rows: List[Dict[str, str]], path: str) -> None:
    if not rows:
        print("[WARN] 저장할 데이터가 없습니다.")
        return

    fieldnames = ["title_ko", "title_en", "year", "rating", "date", "review"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[SAVE] {path} ({len(rows)} rows)")


# =========================================================
# 5. 타겟 정의 (성공 / 호불호 / 실패 구성)
# =========================================================

IMDB_TARGETS = [
    # ---------- 성공 ----------
    {
        "title_ko": "오징어 게임",
        "title_en": "Squid Game",
        "year": 2021,
        "ttid": "tt10919420",
    },
    {
        "title_ko": "더 글로리",
        "title_en": "The Glory",
        "year": 2022,
        "ttid": "tt21344706",
    },
    {
        "title_ko": "기생충",
        "title_en": "Parasite",
        "year": 2019,
        "ttid": "tt6751668",
    },

    # ---------- 호불호 ----------
    {
        "title_ko": "경성 크리처",
        "title_en": "Gyeongseong Creature",
        "year": 2023,
        "ttid": "tt22352854",
    },
    {
        "title_ko": "킹더랜드",
        "title_en": "King the Land",
        "year": 2023,
        "ttid": "tt26693803",
    },
    {
        "title_ko": "지금 우리 학교는 시즌 1",
        "title_en": "All of Us Are Dead Season 1",
        "year": 2022,
        "ttid": "tt14169960",
    },

    # ---------- 실패 ----------
    {
        "title_ko": "택배기사",
        "title_en": "Black Knight",
        "year": 2023,
        "ttid": "tt17013106",
    },
    {
        "title_ko": "야차",
        "title_en": "Yaksha: Ruthless Operations",
        "year": 2022,
        "ttid": "tt15850384",
    },
    {
        "title_ko": "카터",
        "title_en": "Carter",
        "year": 2022,
        "ttid": "tt21237030",
    },
]



# =========================================================
# 6. 메인
# =========================================================

def main():
    driver = create_driver(headless=False)

    all_rows: List[Dict[str, str]] = []
    try:
        for t in IMDB_TARGETS:
            print(
                f"[IMDB-CRAWL] {t['title_ko']} / {t['title_en']} "
                f"({t['year']}) [{t['ttid']}]"
            )
            rows = crawl_imdb_reviews_for_title(
                driver,
                title_ko=t["title_ko"],
                title_en=t["title_en"],
                year=t["year"],
                ttid=t["ttid"],
                max_reviews=1000,
                max_clicks=100,
                click_timeout=6.0,
            )
            print(f"[IMDB-CRAWL]   → {len(rows)}개 수집\n")
            all_rows.extend(rows)
    finally:
        driver.quit()

    save_to_csv(all_rows, "imdb_reviews.csv")


if __name__ == "__main__":
    main()
