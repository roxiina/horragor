"""
HorRAGor – Extracteur Rotten Tomatoes (Selenium)
Scraping dynamique de la section "Horreur" de Rotten Tomatoes.

Champs extraits : title, year, tomatometer_score, audience_score,
                  critics_consensus
"""
import re
import time
from typing import Any

from loguru import logger
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from src.config import settings

# URL de la liste des meilleurs films d'horreur sur RT
_RT_HORROR_URL = "https://www.rottentomatoes.com/browse/movies_in_theaters/genres:horror"
_RT_SEARCH_URL = "https://www.rottentomatoes.com/search?search={query}"
_PAGE_LOAD_WAIT = 10  # secondes


def _build_driver() -> webdriver.Chrome:
    """Instancie un ChromeDriver configuré (headless ou non)."""
    options = Options()
    if settings.selenium_headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Désactiver les indicateurs d'automatisation pour éviter la détection
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if settings.chrome_binary_path:
        options.binary_location = settings.chrome_binary_path

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    # Masquer navigator.webdriver
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


class RottenTomatoesScraper:
    """Scrape les données d'horreur depuis Rotten Tomatoes via Selenium."""

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None

    def extract(self, max_movies: int = 200) -> list[dict[str, Any]]:
        """
        Extrait les films d'horreur depuis la page de navigation RT.

        Args:
            max_movies: nombre maximum de films à scraper.

        Returns:
            Liste de dicts normalisés.
        """
        records: list[dict[str, Any]] = []
        try:
            self._driver = _build_driver()
            records = self._scrape_browse_page(max_movies)
        except WebDriverException as exc:
            logger.error(f"Erreur Selenium critique : {exc}")
        finally:
            if self._driver:
                self._driver.quit()
                self._driver = None

        logger.info(f"Rotten Tomatoes : {len(records)} films extraits")
        return records

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    def _scrape_browse_page(self, max_movies: int) -> list[dict[str, Any]]:
        """
        Navigue sur la page de navigation RT et clique sur 'Load more'
        pour charger davantage de films avant de scraper les vignettes.
        """
        assert self._driver is not None
        records: list[dict[str, Any]] = []

        logger.info(f"Navigation vers {_RT_HORROR_URL}")
        self._driver.get(_RT_HORROR_URL)
        wait = WebDriverWait(self._driver, _PAGE_LOAD_WAIT)

        # Accepter les cookies si une bannière apparaît
        self._dismiss_cookie_banner(wait)

        loaded = 0
        while loaded < max_movies:
            # Scraper les vignettes visibles
            cards = self._driver.find_elements(
                By.CSS_SELECTOR, "div[data-qa='discovery-media-list-item']"
            )
            for card in cards[loaded:]:
                record = self._parse_card(card)
                if record:
                    records.append(record)
                if len(records) >= max_movies:
                    break
            loaded = len(records)

            if loaded >= max_movies:
                break

            # Tentative de clic sur "Load More"
            try:
                load_more_btn = wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "button[data-qa='discovery-more-btn']")
                    )
                )
                self._driver.execute_script("arguments[0].click();", load_more_btn)
                time.sleep(2)
            except TimeoutException:
                logger.debug("Bouton 'Load More' non trouvé, toutes les vignettes chargées.")
                break

        return records

    def _parse_card(self, card) -> dict[str, Any] | None:
        """Extrait les informations d'une vignette de film."""
        try:
            title_el = card.find_element(By.CSS_SELECTOR, "span[data-qa='discovery-media-list-item-title']")
            title = title_el.text.strip()

            year_el = card.find_element(By.CSS_SELECTOR, "span[data-qa='discovery-media-list-item-start-year']")
            year_text = year_el.text.strip()
            year = int(re.sub(r"\D", "", year_text)) if year_text else None

            # Tomatometer score (peut être absent si le film est trop récent)
            tomatometer = self._safe_score(card, "[data-qa='tomatometer']")

            # Lien vers la page détail pour récupérer audience_score et critics_consensus
            link_el = card.find_element(By.CSS_SELECTOR, "a[data-qa='discovery-media-list-item-caption']")
            detail_url = link_el.get_attribute("href") or ""

            return {
                "source": "rotten_tomatoes",
                "tmdb_id": None,
                "imdb_id": None,
                "title": title,
                "original_title": title,
                "overview": None,
                "release_date": f"{year}-01-01" if year else None,
                "vote_average": None,
                "vote_count": None,
                "popularity": None,
                "poster_path": None,
                "tomatometer_score": tomatometer,
                "audience_score": None,     # Chargé en détail si nécessaire
                "critics_consensus": None,  # Chargé en détail si nécessaire
                "budget": None,
                "revenue": None,
                "runtime_minutes": None,
                "_rt_detail_url": detail_url,  # Gardé pour enrichissement ultérieur
            }
        except NoSuchElementException:
            return None

    def scrape_detail(self, detail_url: str) -> dict[str, Any]:
        """
        Visite la page détail d'un film RT pour extraire audience_score
        et critics_consensus.

        Args:
            detail_url: URL complète de la page film sur RT.

        Returns:
            Dict avec les clés ``audience_score`` et ``critics_consensus``.
        """
        result: dict[str, Any] = {"audience_score": None, "critics_consensus": None}
        if not self._driver or not detail_url:
            return result

        try:
            self._driver.get(detail_url)
            wait = WebDriverWait(self._driver, _PAGE_LOAD_WAIT)

            # Audience score
            try:
                aud_el = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-qa='audience-score']")
                    )
                )
                result["audience_score"] = self._parse_score(aud_el.text)
            except TimeoutException:
                pass

            # Critics consensus
            try:
                consensus_el = self._driver.find_element(
                    By.CSS_SELECTOR, "[data-qa='critics-consensus']"
                )
                result["critics_consensus"] = consensus_el.text.strip()
            except NoSuchElementException:
                pass

        except WebDriverException as exc:
            logger.warning(f"Impossible de scraper {detail_url} : {exc}")

        return result

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_score(card, selector: str) -> float | None:
        """Tente d'extraire un score numérique depuis un élément CSS."""
        try:
            el = card.find_element(By.CSS_SELECTOR, selector)
            return RottenTomatoesScraper._parse_score(el.text)
        except NoSuchElementException:
            return None

    @staticmethod
    def _parse_score(text: str) -> float | None:
        """Convertit '85%' ou '8.5' en float."""
        if not text:
            return None
        clean = re.sub(r"[^\d.]", "", text)
        try:
            return float(clean)
        except ValueError:
            return None

    @staticmethod
    def _dismiss_cookie_banner(wait: WebDriverWait) -> None:
        """Accepte la bannière CGU/cookies si présente."""
        try:
            btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#onetrust-accept-btn-handler"))
            )
            btn.click()
            time.sleep(1)
        except TimeoutException:
            pass
