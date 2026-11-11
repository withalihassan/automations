import getpass
import shutil
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

# IMPORTANT: Include http:// or https://.
AWS_URL = "https://aws.amazon.com/"

# Selectors
NAV_SELECTOR = (
    "#global-nav-desktop > div.rggn_24d84766 > div > "
    "ul.rggn_be2a22f9.rggn_0ec3f087 > li:nth-child(2) > a > div"
)

ROOT_SIGNIN_SELECTOR = "button#root_account_signin"
EMAIL_SELECTOR = "#resolving_input"
EMAIL_NEXT_SELECTOR = "#next_button"
PASSWORD_SELECTOR = "#password"
SIGNIN_BUTTON_SELECTOR = "#signin_button"

TROUBLE_SIGNIN_SELECTOR = '[data-testid="troubleshoot-link"]'
ALTERNATIVE_FACTORS_SELECTOR = 'input[type="radio"][value="afa"]'
ALTERNATIVE_FACTORS_NEXT_SELECTOR = (
    'button[data-testid="afa-submit-button"]'
)


def log(profile_number, message):
    """Print messages safely from multiple threads."""
    print(f"[Profile {profile_number}] {message}", flush=True)


def wait_and_click(driver, selector, timeout=45):
    """Wait for an element and click it."""
    element = WebDriverWait(
        driver, timeout, poll_frequency=0.5
    ).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        element,
    )

    try:
        element.click()
    except (
        ElementClickInterceptedException,
        ElementNotInteractableException,
    ):
        # Fallback for elements obstructed by other page elements.
        driver.execute_script("arguments[0].click();", element)

    return element


def switch_to_new_tab_or_stay(
    driver,
    old_handles,
    old_url,
    profile_number,
    timeout=30,
):
    """
    Switch to a newly opened tab if one appears.
    If the link navigates in the same tab, keep using that tab.
    """
    log(profile_number, "Waiting for navigation...")

    try:
        WebDriverWait(
            driver, timeout, poll_frequency=0.5
        ).until(
            lambda d: (
                any(
                    handle not in old_handles
                    for handle in d.window_handles
                )
                or d.current_url != old_url
            )
        )
    except TimeoutException:
        log(
            profile_number,
            "No new tab or URL change detected. "
            "Continuing in the current tab.",
        )
        return

    new_handles = [
        handle
        for handle in driver.window_handles
        if handle not in old_handles
    ]

    if new_handles:
        driver.switch_to.window(new_handles[0])
        log(
            profile_number,
            f"Switched to new tab: {driver.current_url}",
        )
    else:
        log(
            profile_number,
            f"Navigation occurred in the current tab: "
            f"{driver.current_url}",
        )


def select_alternative_factors(driver, profile_number):
    """Select the alternative sign-in option shown by the page."""

    log(profile_number, "Waiting for Trouble signing in link...")

    wait_and_click(
        driver,
        TROUBLE_SIGNIN_SELECTOR,
        timeout=60,
    )

    log(profile_number, "Trouble signing in link clicked.")

    log(profile_number, "Waiting for alternative factors option...")

    radio = WebDriverWait(
        driver, 60, poll_frequency=0.5
    ).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, ALTERNATIVE_FACTORS_SELECTOR)
        )
    )

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});",
        radio,
    )

    try:
        radio.click()
    except (
        ElementClickInterceptedException,
        ElementNotInteractableException,
    ):
        driver.execute_script("arguments[0].click();", radio)

    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script(
            "return arguments[0].checked;",
            radio,
        )
    )

    log(profile_number, "Alternative factors option selected.")

    log(profile_number, "Waiting for Next button...")

    wait_and_click(
        driver,
        ALTERNATIVE_FACTORS_NEXT_SELECTOR,
        timeout=45,
    )

    log(profile_number, "Alternative factors Next button clicked.")


def keep_browser_open(driver, profile_number):
    """Keep the session running until its browser is closed."""
    log(
        profile_number,
        "Workflow reached the stopping point. "
        "Close this Chrome window when finished.",
    )

    while True:
        try:
            if not driver.window_handles:
                break
        except WebDriverException:
            break

        threading.Event().wait(1)


def save_error_screenshot(driver, profile_number):
    """Save diagnostics when a browser session fails."""
    if driver is None:
        return

    try:
        log(profile_number, f"Current URL: {driver.current_url}")
        log(profile_number, f"Page title: {driver.title}")

        filename = f"aws_error_profile_{profile_number}.png"

        if driver.save_screenshot(filename):
            log(profile_number, f"Screenshot saved: {filename}")

    except WebDriverException as error:
        log(profile_number, f"Could not save diagnostics: {error}")


def run_profile(profile_number, email, password):
    """Run the workflow in an independent Chrome session."""
    driver = None

    # Each session receives its own Chrome profile directory.
    profile_dir = tempfile.mkdtemp(
        prefix=f"aws_chrome_profile_{profile_number}_"
    )

    try:
        log(profile_number, "Starting Chrome...")

        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        driver = webdriver.Chrome(options=options)
        driver.maximize_window()
        driver.set_page_load_timeout(60)

        # STEP 1: Open the local AWS portal.
        log(profile_number, f"Opening {AWS_URL}...")
        driver.get(AWS_URL)

        log(
            profile_number,
            f"Page loaded. Title: {driver.title!r}",
        )

        # STEP 2: Click the navigation link.
        old_handles = set(driver.window_handles)
        old_url = driver.current_url

        log(profile_number, "Clicking navigation sign-in link...")

        wait_and_click(
            driver,
            NAV_SELECTOR,
            timeout=60,
        )

        # STEP 3: Switch tabs if a new one was opened.
        switch_to_new_tab_or_stay(
            driver,
            old_handles,
            old_url,
            profile_number,
        )

        # STEP 4: Open root-user sign-in.
        log(profile_number, "Waiting for root-user sign-in button...")

        wait_and_click(
            driver,
            ROOT_SIGNIN_SELECTOR,
            timeout=60,
        )

        # STEP 5: Enter email.
        log(profile_number, "Waiting for email field...")

        email_field = WebDriverWait(
            driver, 60, poll_frequency=0.5
        ).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, EMAIL_SELECTOR)
            )
        )

        email_field.clear()
        email_field.send_keys(email)

        # STEP 6: Submit email.
        log(profile_number, "Submitting email...")

        wait_and_click(
            driver,
            EMAIL_NEXT_SELECTOR,
            timeout=45,
        )

        # STEP 7: Allow manual CAPTCHA completion.
        log(
            profile_number,
            "Solve any CAPTCHA manually in this Chrome window.",
        )
        log(
            profile_number,
            "Waiting up to 10 minutes for the password field...",
        )

        password_field = WebDriverWait(
            driver,
            600,
            poll_frequency=1,
        ).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, PASSWORD_SELECTOR)
            )
        )

        # STEP 8: Enter password.
        log(profile_number, "Entering password...")

        password_field.clear()
        password_field.send_keys(password)

        # STEP 9: Submit password.
        log(profile_number, "Clicking Sign in...")

        wait_and_click(
            driver,
            SIGNIN_BUTTON_SELECTOR,
            timeout=45,
        )

        # STEP 10: Open the sign-in troubleshooting option.
        log(
            profile_number,
            "Opening alternative sign-in options...",
        )

        select_alternative_factors(driver, profile_number)

        # STOP at the requested point.
        keep_browser_open(driver, profile_number)

    except TimeoutException as error:
        log(profile_number, f"TIMEOUT: {error}")
        save_error_screenshot(driver, profile_number)

    except WebDriverException as error:
        log(profile_number, f"SELENIUM/BROWSER ERROR: {error}")
        save_error_screenshot(driver, profile_number)

    except Exception as error:
        log(profile_number, f"UNEXPECTED ERROR: {error}")
        traceback.print_exc()
        save_error_screenshot(driver, profile_number)

    finally:
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass

        shutil.rmtree(profile_dir, ignore_errors=True)

        log(profile_number, "Session ended; temporary profile cleaned.")


def main():
    # Ask how many independent Chrome sessions to launch.
    while True:
        try:
            profile_count = int(
                input(
                    "How many Chrome profiles do you want to open? "
                ).strip()
            )

            if profile_count < 1:
                print("Enter a number greater than zero.")
                continue

            break

        except ValueError:
            print("Invalid input. Enter a whole number, such as 1 or 2.")

    # Credentials are requested once and shared across these sessions.
    email = input("Enter AWS email: ").strip()
    password = getpass.getpass("Enter AWS password: ")

    if not email or not password:
        print("Email and password are required.")
        return

    print(
        f"\nLaunching {profile_count} independent Chrome session(s)...",
        flush=True,
    )

    # All requested sessions run concurrently.
    with ThreadPoolExecutor(
        max_workers=profile_count,
        thread_name_prefix="AWS-Profile",
    ) as executor:

        futures = [
            executor.submit(
                run_profile,
                profile_number,
                email,
                password,
            )
            for profile_number in range(1, profile_count + 1)
        ]

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                print(
                    f"A session could not complete: {error}",
                    flush=True,
                )

    print("\nAll requested sessions have finished.")


if __name__ == "__main__":
    main()