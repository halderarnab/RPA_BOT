from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from time import sleep
from typing import Callable, Iterable, Any

from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from .config import BotConfig
from .excel_reader import DataRow
from .state import BotState
from .validators import validate_row

PromptFn = Callable[[str, str], str | None]
StatusFn = Callable[[str], None]


class CpcbWasteTyreBot:
    def __init__(
        self,
        config: BotConfig,
        state: BotState,
        purchase_invoice_folder: Path,
        sales_invoice_folder: Path,
        prompt: PromptFn,
        status: StatusFn,
    ) -> None:
        self.config = config
        self.state = state
        self.purchase_invoice_folder = purchase_invoice_folder
        self.sales_invoice_folder = sales_invoice_folder
        self.prompt = prompt
        self.status = status
        self.driver: WebDriver | None = None
        self.log = logging.getLogger(self.__class__.__name__)

    def open_browser(self) -> None:
        if not self.config.portal_url or self.config.portal_url.startswith("https://example-"):
            raise ValueError("Set the real portal_url in config.json before opening the browser.")
        if self.driver is None:
            self.driver = self._create_driver()
        self.status(f"Opening portal: {self.config.portal_url}")
        self.driver.get(self.config.portal_url)

    def login(self, login_id: str, password: str) -> None:
        self.open_browser()
        self._require_selector_group(["login_id", "password", "captcha_input", "login_button", "otp_input", "otp_submit_button", "role_recycler"], "login")
        while(not self._is_visible("otp_input", timeout = 2)):
            self._select_login_role("recycler")
            self._type_first("login_id", login_id)
            self._type_first("password", password)

            captcha = self.prompt("Captcha Required", "Enter the captcha shown in the browser.")
            if captcha:
                self._type_first("captcha_input", captcha)

            self._click_first("login_button")
            
        while(self._is_visible("otp_input", timeout = 2)):
            otp = self.prompt("OTP Required", "Enter the OTP received on the registered mobile number.")
            if otp:
                self._type_first("otp_input", otp)
                self._click_first("otp_submit_button")

        self.log.info("Login flow submitted")
        self.status("Login flow submitted")

    def logout(self) -> None:
        if self.driver is None:
            self.status("Browser is not open")
            return
        element = self._find_with_retry(self.config.selectors.get("logout_button")[0])
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        self._click_first("logout_button")
        self.log.info("Logout clicked")
        self.status("Logout clicked")

    def process_dataset(self, dataset: str, rows: list[DataRow]) -> None:
        self._require_dataset_selectors(dataset)
        navigation = {
            "procurement": ("menu_view_procurement", "button_add_procurement"),
            "recycling": ("menu_recycled_data", "button_add_recycling"),
            "sales": ("menu_create_epr_credits", None),
        }
        menu_selector, add_selector = navigation[dataset]
        self._click_first(menu_selector)

        for row in rows:
            if self.state.is_done(dataset, row.row_id):
                continue
            try:
                errors = validate_row(dataset, row.values, self._invoice_folder_for(dataset))
                if errors:
                    raise ValueError("; ".join(errors))

                if add_selector:
                    self._click_first(add_selector)

                if dataset == "sales":
                    self._select_sales_tab(row.values)

                self._fill_fields(dataset, row.values)
                self._submit(dataset)
                message = self._capture_status_message(dataset)
                self.state.mark_done(dataset, row.row_id)
                self.log.info("%s row %s completed: %s", dataset, row.row_number, message)
                self.status(f"{dataset.title()} row {row.row_number} completed")
            except Exception as exc:
                self.state.mark_failed(dataset, row.row_id)
                self.log.exception("%s row %s failed: %s", dataset, row.row_number, exc)
                self.status(f"{dataset.title()} row {row.row_number} failed. See errors.")

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def _create_driver(self) -> WebDriver:
        if self.config.browser.lower() != "chrome":
            raise ValueError("Only Chrome is configured in this scaffold.")
        options = ChromeOptions()
        if self.config.headless:
            options.add_argument("--headless=new")
        options.add_argument("--start-maximized")
        return webdriver.Chrome(options=options)

    def _fill_fields(self, dataset: str, values: dict[str, Any]) -> None:
        field_selectors = self.config.field_selectors.get(dataset, {})
        for selector_key, selectors in field_selectors.items():
            if selector_key not in values:
                continue
            value = values[selector_key]
            if selector_key == "invoice_file":
                value = str(self._invoice_folder_for(dataset) / str(value).strip())
            self._set_field(selectors, value, selector_key)

    def _invoice_folder_for(self, dataset: str) -> Path:
        if dataset == "sales":
            return self.sales_invoice_folder
        return self.purchase_invoice_folder

    def _select_sales_tab(self, values: dict[str, Any]) -> None:
        sales_type = str(values.get("sales_type") or "domestic").strip().lower()
        key = "tab_import" if sales_type == "import" else "tab_domestic"
        self._click_first(key)

    def _select_login_role(self, role: str) -> None:
        normalized_role = role.strip().lower()
        allowed_roles = {"producer", "recycler", "retreader", "admin"}
        if normalized_role not in allowed_roles:
            raise ValueError(f"Login role must be one of: {', '.join(sorted(allowed_roles))}")

        selector_key = f"role_{normalized_role}"
        self._click_first(selector_key)
        self.log.info("Selected login role: %s", role)

    def _submit(self, dataset: str) -> None:
        if dataset == "recycling":
            self._click_any(self.config.selectors.get("save_button", []), "submit button")
        else:
            self._click_any(self.config.selectors.get("submit_button", []), "submit button")

    def _capture_status_message(self, dataset: str) -> str:
        # Recycling - //*[@id="content-wrapper"]/div[2]/div
        # Sales - //*[@id="content"]/div[2]/div/p[text()='Invoice updated successfully!']
        if dataset == "procurement":
            procurement_success_message = self.config.selectors.get("procurement_success_message")
            try:
                element = self._find_with_retry(procurement_success_message, timeout=1)
                text = element.text.strip()
                if text:
                    return text
            except Exception as exc:
                self.log.warning("Failed: Procurement success message not found. " + exc)
        elif dataset == "recycling":
            recycling_success_message = self.config.selectors.get("recycling_success_message")
            try:
                element = self._find_with_retry(recycling_success_message, timeout=2)
                text = element.text.strip()
                if text:
                    return text
            except Exception as exc:
                self.log.warning("Failed: Recycling success message not found. " + exc)
        else:
            sales_success_message = self.config.selectors.get("sales_success_message")
            try:
                element = self._find_with_retry(sales_success_message, timeout=2)
                text = element.text.strip()
                if text:
                    return text
            except Exception as exc:
                self.log.warning("Failed: Sales success message not found. " + exc)
        return "No status message detected"

    def _type_first(self, selector_key: str, value: str) -> None:
        self._set_field(self.config.selectors.get(selector_key, []), value, selector_key)

    def _click_first(self, selector_key: str) -> None:
        count  = 0
        while(not self._is_clickable(selector_key, timeout = 5) and count < 10):
            # print(str(count) + ", Waiting for clickability of: " + selector_key)
            count += 1
            sleep(1)
        if(not self._is_clickable(selector_key, timeout = 5)):
            raise TimeoutException(selector_key + " button is not clickable")
        self._click_any(self.config.selectors.get(selector_key, []), selector_key)

    def _click_any(self, selectors: Iterable[str], label: str) -> None:
        last_error: Exception | None = None
        for selector in selectors:
            try:
                # element = self._find_with_retry(selector)
                # element.click()
                self._click_with_retry(selector)
                return
            except Exception as exc:
                last_error = exc
        raise TimeoutException(f"Could not find/click {label} - {selectors}") from last_error
    
    def _click_with_retry(
        self,
        selector: str,
        attempts: int = 5,
        timeout: int | None = None,
        pause_seconds: float = 1.0,
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._wait_for_loaders()
                element = self._find_with_retry(selector, attempts=1, timeout=timeout)
                if self.driver is None:
                    raise RuntimeError("Browser is not open")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                self._wait_for_loaders()
                element.click()
                return
            except ElementClickInterceptedException as exc:
                last_error = exc
                self.log.warning("Click attempt %s/%s intercepted for selector %s: %s", attempt, attempts, selector, exc)
                if attempt < attempts:
                    sleep(pause_seconds)
            except Exception as exc:
                last_error = exc
                self.log.warning("Click attempt %s/%s FAILED for selector %s: %s", attempt, attempts, selector, exc)
                if attempt < attempts:
                    sleep(pause_seconds)
        raise TimeoutException(f"Could not click element after {attempts} attempts: {selector}") from last_error

    def _set_field(self, selectors: Iterable[str], value: Any, selector_key: str | None = None) -> None:
        last_error: Exception | None = None
        for selector in selectors:
            try:
                element = self._find_with_retry(selector)

                tag = element.tag_name.lower()
                input_type = (element.get_attribute("type") or "").lower()
                element_class = (element.get_attribute("class") or "").lower()
                # print(f"{input_type} - {tag} - {selector_key} - {selector} - {element_class}")

                if input_type == "file":
                    element.send_keys(str(value))
                elif "select-dropdown" in element_class.lower():
                    self._click_with_retry(selector)
                    select_option_selector = self.config.selectors.get("select_options") + "//span[contains(text(),'" + str(value) + "')]"
                    option = self._find_with_retry(select_option_selector)
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
                    self._click_with_retry(select_option_selector)
                elif "datepicker" in element_class.lower():
                    self._click_with_retry(selector)

                    dt = datetime.strptime(value, "%d/%m/%Y")
                    day = dt.day
                    month = dt.month
                    year = dt.year

                    month_dropdown = self._find_with_retry(self.config.selectors.get("month_dropdown"))
                    Select(month_dropdown).select_by_value(str(int(month) - 1))
                    
                    year_dropdown = self._find_with_retry(self.config.selectors.get("year_dropdown"))
                    Select(year_dropdown).select_by_value(str(year))

                    day_selector = self.config.selectors.get("select_day") + "[text()='" + str(day) + "']"
                    self._click_with_retry(day_selector)
                elif "table" in tag.lower():
                    if str(value) == "":
                        return
                    self._set_product_weight(selector, value, selector_key)
                else:
                    element.clear()
                    element.send_keys(str(value))
                return
            except Exception as exc:
                last_error = exc
        raise TimeoutException(f"Could not fill field: {selector_key} - {value} - {selectors}") from last_error
    
    def _set_product_weight(self, selector: str, value: Any, selector_key: str | None = None) -> None:
        product_map = {
            "reclaimed rubber": "Reclaimed Rubber",
            "recovered carbon black": "Recovered Carbon Black",
            "crumb rubber modified bitumen": "Crumb Rubber Modified Bitumen",
            "crumb rubber": "Crumb Rubber",
            "pyrolysis oil or char": "Pyrolysis oil or Char "
        }

        products_weights = str(value).strip().split(",")
        # print(products_weights)
        for item in products_weights:
            product, weight = item.strip().split(":")
            product = product_map[product.strip().lower()]
            weight = weight.strip()
            # print(product + " : " + weight)
            if product == "Pyrolysis oil or Char ":
                # weight is of the form "Batch-10" or "Continuous-5"
                ptype, weight = weight.split("-")
                ptype = ptype.strip()
                weight = weight.strip()
                if ptype.lower() == "continuous":
                    ptype_selector = "//*[@id='choice_2']"
                    self._click_with_retry(ptype_selector)
                # print(ptype + " && " + weight)
            
            weight_selector = selector + "/tbody/tr//*[text()='" + product + "']/following-sibling::td[4]/input"
            # print(weight_selector)
            element = self._find_with_retry(weight_selector)
            element.clear()
            element.send_keys(str(weight))

    def _find(self, selector: str, timeout: int | None = None) -> WebElement:
        if self.driver is None:
            raise RuntimeError("Browser is not open")
        wait = WebDriverWait(self.driver, timeout or self.config.timeout_seconds)
        by, value = self._selector_type(selector)
        return wait.until(EC.presence_of_element_located((by, value)))
    
    def _find_with_retry(
        self,
        selector: str,
        attempts: int = 5,
        timeout: int | None = None,
        pause_seconds: float = 1.0,
    ) -> WebElement:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._find(selector, timeout)
            except Exception as exc:
                last_error = exc
                self.log.warning("Find attempt %s/%s failed for selector %s: %s", attempt, attempts, selector, exc)
                if attempt < attempts:
                    sleep(pause_seconds)
        raise TimeoutException(f"Could not find element after {attempts} attempts: {selector}") from last_error

    def _is_visible(self, selector_key: str, dataset: str = None, timeout: int = 5) -> bool:
        if self.driver is None:
            return False
        selectors = self.config.selectors.get(selector_key)
        for selector in selectors:
            try:
                by, value = self._selector_type(selector)
                wait = WebDriverWait(self.driver, timeout)
                wait.until(EC.visibility_of_element_located((by, value)))
                return True
            except TimeoutException:
                continue
        return False
    
    def _is_clickable(self, selector_key: str, timeout: int = 2) -> bool:
        if self.driver is None:
            return False

        selectors = self.config.selectors.get(selector_key, [])
        for selector in selectors:
            try:
                by, value = self._selector_type(selector)
                wait = WebDriverWait(self.driver, timeout)
                wait.until(EC.element_to_be_clickable((by, value)))
                return True
            except TimeoutException:
                continue
        return False
    
    def _wait_for_loaders(self, timeout: int | None = None) -> None:
        if self.driver is None:
            return

        selectors = self.config.selectors.get("loader_overlays", [])
        for selector in selectors:
            try:
                by, value = self._selector_type(selector)
                wait = WebDriverWait(self.driver, timeout or self.config.timeout_seconds)
                wait.until(EC.invisibility_of_element_located((by, value)))
            except TimeoutException:
                self.log.warning("Loader still visible after timeout: %s", selector)

    def _selector_type(self, selector: str) -> tuple[str, str]:
        stripped = selector.strip()
        if stripped.startswith("//") or stripped.startswith("("):
            return By.XPATH, stripped
        return By.CSS_SELECTOR, stripped

    def _require_selector_group(self, keys: list[str], label: str) -> None:
        missing = [key for key in keys if not self.config.selectors.get(key)]
        if missing:
            raise ValueError(f"Configure {label} selectors in config.json: {', '.join(missing)}")

    def _require_dataset_selectors(self, dataset: str) -> None:
        field_selectors = self.config.field_selectors.get(dataset, {})
        if not field_selectors:
            raise ValueError(f"Configure field_selectors.{dataset} in config.json before submitting rows.")

        missing_fields = [
            field
            for field in field_selectors
            if not field_selectors.get(field)
        ]
        if missing_fields:
            raise ValueError(f"Empty selectors for {dataset} fields: {', '.join(missing_fields)}")

        navigation_requirements = {
            "procurement": ["menu_view_procurement", "button_add_procurement"],
            "recycling": ["menu_recycled_data", "button_add_recycling"],
            "sales": ["menu_create_epr_credits", "tab_domestic", "tab_import"],
        }
        self._require_selector_group(navigation_requirements[dataset], f"{dataset} navigation")
