#!/usr/bin/env python3
"""
Samsung login with simplified solver flow + robust Next-click logic.
If solver clicked but Next can't be found, the script will refresh the page
and restart the login flow up to REFRESH_RESTARTS times.

Change made: before typing the account/email ensure the account field is empty.
If it's not empty (autofill), clear it robustly, then type the provided email.
Everything else in the script is preserved.
"""
import os
import time
import random
import ssl
import certifi
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)

# ---------------- Configuration ----------------
SAMSUNG_INTRO_URL    = "https://v3.account.samsung.com/dashboard/intro"
CHROME_MAJOR_VERSION = 141
FIXED_PASSWORD       = "@Smsng#860"
DEFAULT_WAIT_SECONDS = 15
SCREENSHOT_ON_ERROR  = True
IFRAME_MAX_DEPTH     = 5
# how many times to refresh+restart when Next cannot be found after solver click
REFRESH_RESTARTS     = 3
# wait after solver click before attempting Next/Sign in (as requested)
AFTER_SOLVER_WAIT    = 4.0
# -----------------------------------------------

# ---------- Helpers ----------
def human_delay(a=0.08, b=0.18):
    time.sleep(random.uniform(a, b))

def human_type(el, text, min_delay=0.03, max_delay=0.12):
    try:
        el.clear()
    except Exception:
        pass
    for ch in text:
        el.send_keys(ch)
        time.sleep(random.uniform(min_delay, max_delay))
    human_delay(0.08, 0.18)

def take_screenshot(driver, name="error_screenshot.png"):
    try:
        path = os.path.join(os.getcwd(), name)
        driver.save_screenshot(path)
        print(f"[+] Screenshot saved: {path}")
    except Exception as e:
        print(f"[WARN] Screenshot failed: {e}")

def safe_js_click(driver, el):
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception as e:
        print(f"[WARN] JS click failed: {e}")
        return False

def safe_action_click(driver, el):
    try:
        actions = ActionChains(driver)
        actions.move_to_element(el).pause(random.uniform(0.05,0.18)).click(el).perform()
        return True
    except Exception:
        return safe_js_click(driver, el)

def wait_for_page_ready(driver, timeout=12):
    """Wait for document.readyState == 'complete' (polling)."""
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                state = driver.execute_script("return document.readyState")
            except Exception:
                state = None
            if state == "complete":
                # small extra delay to let dynamic content mount
                human_delay(0.5, 1.0)
                return True
            time.sleep(0.25)
    except Exception:
        pass
    return False

# ---------- Cookie close ----------
def close_cookie_strict(driver, wait_seconds=3):
    sel = "button.MuiButtonBase-root.MuiIconButton-root.MuiIconButton-sizeMedium.css-10snoxe"
    try:
        el = WebDriverWait(driver, wait_seconds).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
    except TimeoutException:
        return False
    try:
        try:
            img = el.find_element(By.TAG_NAME, "img")
            src = img.get_attribute("src") or ""
            if "close.svg" not in src and "close" not in src.lower():
                print("[WARN] cookie-close img doesn't appear correct; skipping.")
                return False
        except NoSuchElementException:
            print("[WARN] cookie-close found but no <img>; skipping.")
            return False
        print("[*] Clicking strict cookie-close button.")
        safe_action_click(driver, el)
        human_delay(0.35, 0.6)
        return True
    except Exception as e:
        print(f"[WARN] Error clicking cookie-close: {e}")
        return False

# ---------- Deep iframe search utilities ----------
def _switch_to_default_and_path(driver, path):
    driver.switch_to.default_content()
    for idx in path:
        driver.switch_to.frame(idx)

def find_frame_path_with_selector(driver, selectors, max_depth=IFRAME_MAX_DEPTH):
    def _scan(path, depth):
        if depth > max_depth:
            return None
        try:
            _switch_to_default_and_path(driver, path)
        except Exception:
            return None
        for sel in selectors:
            try:
                if driver.find_elements(By.CSS_SELECTOR, sel):
                    return list(path)
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames = []
        for i in range(len(frames)):
            res = _scan(path + [i], depth + 1)
            if res is not None:
                return res
        return None
    return _scan([], 0)

def find_element_in_frame_by_path(driver, path, selector, timeout=2):
    try:
        _switch_to_default_and_path(driver, path)
        el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        return el
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return None

# ---------- Robust click strategies ----------
def click_element_with_strategies(driver, el):
    try:
        actions = ActionChains(driver)
        actions.move_to_element(el).pause(0.12).click(el).perform()
        human_delay(0.3, 0.6)
        return True
    except Exception as e:
        print(f"[WARN] ActionChains click failed: {e}")
    try:
        driver.execute_script("arguments[0].click();", el)
        human_delay(0.25, 0.5)
        return True
    except Exception as e:
        print(f"[WARN] JS click failed: {e}")
    try:
        driver.execute_script("""
            const el = arguments[0];
            const rect = el.getBoundingClientRect();
            const cx = rect.left + rect.width/2;
            const cy = rect.top + rect.height/2;
            function triggerMouse(type, x, y){
                const evt = new MouseEvent(type, {
                    view: window, bubbles: true, cancelable: true,
                    clientX: x, clientY: y
                });
                el.dispatchEvent(evt);
                document.elementFromPoint(x,y)?.dispatchEvent(evt);
            }
            triggerMouse('mouseover', cx, cy);
            triggerMouse('mousemove', cx, cy);
            triggerMouse('mousedown', cx, cy);
            triggerMouse('mouseup', cx, cy);
            triggerMouse('click', cx, cy);
        """, el)
        human_delay(0.4, 0.8)
        return True
    except Exception as e:
        print(f"[WARN] synthetic mouse events failed: {e}")
    return False

# ---------- Aggressive solver click helper ----------
def click_solver_by_any_means(driver, checkbox_path=None, checkbox_selector=".recaptcha-checkbox, #recaptcha-anchor"):
    # 1) top-level solver id
    try:
        top = driver.find_elements(By.CSS_SELECTOR, "#solver-button")
        if top:
            print("[*] Found top-level #solver-button; clicking.")
            try:
                click_element_with_strategies(driver, top[0])
                return True
            except Exception:
                pass
    except Exception:
        pass

    # 2) deep iframe search for solver-button
    try:
        solver_path = find_frame_path_with_selector(driver, ["#solver-button"], max_depth=IFRAME_MAX_DEPTH)
        if solver_path is not None:
            print(f"[*] Found solver-button inside iframe path {solver_path}; clicking inside that frame.")
            el = find_element_in_frame_by_path(driver, solver_path, "#solver-button", timeout=2)
            if el:
                _switch_to_default_and_path(driver, solver_path)
                try:
                    click_element_with_strategies(driver, el)
                    driver.switch_to.default_content()
                    return True
                except Exception:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
    except Exception:
        pass

    # 3) click container .button-holder.help-button-holder (top-level or inside frame)
    try:
        containers = driver.find_elements(By.CSS_SELECTOR, ".button-holder.help-button-holder")
        if containers:
            print("[*] Found .button-holder.help-button-holder container top-level; clicking it.")
            try:
                click_element_with_strategies(driver, containers[0])
                return True
            except Exception:
                pass
        else:
            cont_path = find_frame_path_with_selector(driver, [".button-holder.help-button-holder"], max_depth=IFRAME_MAX_DEPTH)
            if cont_path is not None:
                print(f"[*] Found container in iframe path {cont_path}; clicking container.")
                c_el = find_element_in_frame_by_path(driver, cont_path, ".button-holder.help-button-holder", timeout=2)
                if c_el:
                    _switch_to_default_and_path(driver, cont_path)
                    try:
                        click_element_with_strategies(driver, c_el)
                        driver.switch_to.default_content()
                        return True
                    except Exception:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
    except Exception:
        pass

    # 4) viewport click near checkbox center using elementFromPoint
    try:
        if checkbox_path is not None:
            print("[*] Using viewport click fallback near recaptcha checkbox center (elementFromPoint).")
            _switch_to_default_and_path(driver, checkbox_path)
            rect = driver.execute_script("""
                const sel = arguments[0];
                const el = document.querySelector(sel);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {left: r.left, top: r.top, width: r.width, height: r.height, cx: r.left + r.width/2, cy: r.top + r.height/2};
            """, checkbox_selector)
            driver.switch_to.default_content()
            if rect:
                offsets = [
                    (rect['cx'] + rect['width'] + 20, rect['cy']),
                    (rect['cx'] + 40, rect['cy']),
                    (rect['cx'], rect['cy'] + rect['height'] + 30),
                    (rect['cx'], rect['cy'] - 30)
                ]
                for (x, y) in offsets:
                    try:
                        print(f"[*] Trying elementFromPoint click at viewport coords ({x},{y}).")
                        clicked = driver.execute_script("""
                            const x = arguments[0], y = arguments[1];
                            const el = document.elementFromPoint(x, y);
                            if(el){
                                el.scrollIntoView({block:'center', inline:'center'});
                                try{ el.click(); return true; }catch(e){}
                                function trigger(t, px, py){
                                    const ev = new MouseEvent(t, {view: window, bubbles: true, cancelable: true, clientX: px, clientY: py});
                                    el.dispatchEvent(ev);
                                }
                                trigger('mouseover', x, y);
                                trigger('mousemove', x, y);
                                trigger('mousedown', x, y);
                                trigger('mouseup', x, y);
                                trigger('click', x, y);
                                return true;
                            }
                            return false;
                        """, int(x), int(y))
                        if clicked:
                            human_delay(0.5, 1.0)
                            return True
                    except Exception as e:
                        print(f"[WARN] elementFromPoint click attempt failed: {e}")
    except Exception:
        pass

    print("[WARN] Solver button could not be clicked by any strategy.")
    return False

# ---------- recaptcha handling simplified (no polling) ----------
def handle_recaptcha_and_click_solver(driver):
    """
    Try to locate recaptcha checkbox, click it, then try to click solver UI.
    DOES NOT poll for g-recaptcha-response. Returns tuple:
      (captcha_found_bool, solver_clicked_bool)
    """
    selectors = [".recaptcha-checkbox", "#recaptcha-anchor"]
    print("[*] Scanning briefly for recaptcha checkbox/iframe...")
    path = None
    scan_deadline = time.time() + 4
    while time.time() < scan_deadline:
        path = find_frame_path_with_selector(driver, selectors, max_depth=IFRAME_MAX_DEPTH)
        if path is not None:
            break
        time.sleep(0.35)
    if path is None:
        print("[*] No recaptcha iframe found.")
        return False, False

    print(f"[*] Found recaptcha checkbox in iframe path: {path} — attempting checkbox click.")
    el = find_element_in_frame_by_path(driver, path, ".recaptcha-checkbox, #recaptcha-anchor", timeout=2)
    clicked_checkbox = False
    try:
        _switch_to_default_and_path(driver, path)
        if el is None:
            try:
                el = driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox, #recaptcha-anchor")
            except Exception:
                el = None
        if el:
            clicked_checkbox = click_element_with_strategies(driver, el)
        else:
            try:
                driver.execute_script("""
                    const e = document.querySelector('.recaptcha-checkbox, #recaptcha-anchor');
                    if(e){ e.scrollIntoView({block:'center', inline:'center'}); e.click(); }
                """)
                human_delay(0.4, 0.9)
                clicked_checkbox = True
            except Exception:
                clicked_checkbox = False
    except Exception as e:
        print(f"[WARN] Exception while clicking checkbox: {e}")
        clicked_checkbox = False
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    if clicked_checkbox:
        print("[+] Checkbox click attempted.")
    else:
        print("[WARN] Checkbox click not made (maybe already clicked or not present).")

    # Try solver
    solver_clicked = click_solver_by_any_means(driver, checkbox_path=path)
    if solver_clicked:
        print("[*] Solver button click attempted.")
    else:
        print("[*] Solver button not found/clicked.")

    return True, solver_clicked

# ---------- Next/Sign helpers (robust) ----------
def click_next_button(driver):
    """Robust attempts to find and click Next. Returns True if clicked."""
    # primary selectors
    selectors = [
        ("css", "button[data-testid='test-button-next']"),
        ("xpath", "//button[@data-log-id='next' or normalize-space(.)='Next']"),
        ("css", "button[type='submit'][data-log-id='next']"),
    ]
    for kind, sel in selectors:
        try:
            if kind == "css":
                nxt = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            else:
                nxt = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, sel)))
            print("[*] Clicking Next ({})".format(sel))
            safe_action_click(driver, nxt)
            human_delay(0.6, 1.2)
            return True
        except Exception:
            pass

    # fallback: look for visible button whose text contains "Next"
    try:
        cand = driver.find_elements(By.XPATH, "//button[contains(normalize-space(.),'Next')]")
        for b in cand:
            try:
                if b.is_displayed() and b.is_enabled():
                    print("[*] Clicking Next by text-match fallback.")
                    safe_action_click(driver, b)
                    human_delay(0.6, 1.2)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # fallback: search inside iframes for the test-button-next
    try:
        frame_path = find_frame_path_with_selector(driver, ["button[data-testid='test-button-next']", "button[data-log-id='next']", "button[type='submit'][data-log-id='next']"], max_depth=IFRAME_MAX_DEPTH)
        if frame_path is not None:
            print(f"[*] Found Next inside iframe path {frame_path}; clicking inside that frame.")
            el = find_element_in_frame_by_path(driver, frame_path, "button[data-testid='test-button-next'], button[data-log-id='next'], button[type='submit'][data-log-id='next']", timeout=2)
            if el:
                _switch_to_default_and_path(driver, frame_path)
                try:
                    click_element_with_strategies(driver, el)
                    driver.switch_to.default_content()
                    human_delay(0.6, 1.2)
                    return True
                except Exception:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
    except Exception:
        pass

    print("[WARN] Next button not found when attempting retry.")
    return False

def click_sign_in_button(driver):
    try:
        btn = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Sign in']")))
        print("[*] Clicking Sign in.")
        safe_action_click(driver, btn)
        human_delay(0.6, 1.0)
        return True
    except Exception:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button.css-hrwkno")
            print("[*] Clicking Sign in fallback (css-hrwkno).")
            safe_action_click(driver, btn)
            human_delay(0.6, 1.0)
            return True
        except Exception:
            print("[ERROR] Sign in button not found.")
            return False

def fill_account_and_remember_then_next(driver, email):
    try:
        acct = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.visibility_of_element_located((By.ID, "account")))
        print("[*] Located account/email input.")
    except Exception:
        print("[ERROR] account input not visible.")
        return False

    # ---- NEW: if field has value (autofill), clear it robustly ----
    try:
        current_val = acct.get_attribute("value") or ""
        if current_val.strip() != "":
            print(f"[*] Account input already has value (autofill detected): '{current_val[:60]}...' — clearing it.")
            try:
                acct.clear()
                human_delay(0.08, 0.18)
            except Exception:
                pass
            # send CTRL+A then BACKSPACE to force-clear
            try:
                acct.send_keys(Keys.CONTROL + "a")
                acct.send_keys(Keys.BACKSPACE)
                human_delay(0.08, 0.12)
            except Exception:
                pass
            # final fallback: set via JS
            try:
                driver.execute_script("arguments[0].value = '';", acct)
                human_delay(0.08, 0.12)
            except Exception:
                pass
            # verify cleared
            try:
                still = acct.get_attribute("value") or ""
                if still.strip() != "":
                    print("[WARN] Account input still has content after clear attempts: attempting to focus and clear again.")
                    try:
                        acct.click()
                        acct.send_keys(Keys.END)
                        acct.send_keys(Keys.BACKSPACE * 6)
                        acct.send_keys(Keys.CONTROL + "a")
                        acct.send_keys(Keys.DELETE)
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            print("[*] Account input empty — proceeding to type.")
    except Exception as e:
        print(f"[WARN] Could not read account input value safely: {e}")

    # Type the provided email
    try:
        print("[*] Typing account/email.")
        human_type(acct, email)
    except Exception as e:
        print(f"[ERROR] Failed to type account/email: {e}")
        return False

    # Try several strategies to click "Remember my ID"
    clicked_remember = False
    try:
        label = driver.find_element(By.XPATH, "//label[.//span[normalize-space(text())='Remember my ID']]")
        safe_action_click(driver, label); human_delay(0.12, 0.28); clicked_remember = True
    except Exception:
        pass
    if not clicked_remember:
        try:
            s = driver.find_element(By.CSS_SELECTOR, "span[data-testid='test-checkbox-signin-remembermyID']")
            safe_action_click(driver, s); human_delay(0.12, 0.28); clicked_remember = True
        except Exception:
            pass
    if not clicked_remember:
        try:
            cb = driver.find_element(By.XPATH, "//label[.//span[contains(normalize-space(.),'Remember my ID')]]//input[@type='checkbox']")
            safe_action_click(driver, cb); human_delay(0.12, 0.28); clicked_remember = True
        except Exception:
            pass

    if clicked_remember:
        print("[+] Remember my ID clicked/attempted.")
    else:
        print("[WARN] Remember my ID not located; continuing.")

    return click_next_button(driver)

def ensure_password_field_visible_or_retry_next(driver):
    try:
        WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.visibility_of_element_located((By.ID, "password")))
        return True
    except Exception:
        # try click Next again within DEFAULT_WAIT_SECONDS
        try:
            print("[*] Password not visible: trying Next again.")
            if click_next_button(driver):
                WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.visibility_of_element_located((By.ID, "password")))
                return True
            return False
        except Exception:
            return False

def fill_password_and_signin(driver):
    try:
        pw = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.visibility_of_element_located((By.ID, "password")))
        print("[*] Typing password.")
        human_type(pw, FIXED_PASSWORD)
    except Exception:
        print("[ERROR] password input not visible.")
        return False

    try:
        signin = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='test-button-signin']")))
        print("[*] Clicking Sign in (final).")
        safe_action_click(driver, signin)
        human_delay(0.8, 1.2)
    except Exception:
        print("[ERROR] final Sign in button not found.")
        return False

    # NEW: Wait for page load properly, then look for Stay signed in (exact container -> button).
    # First wait for the page to enter a 'ready' state.
    print("[*] Waiting for page to load after Sign in...")
    wait_for_page_ready(driver, timeout=12)

    # attempt to locate the Stay signed in button inside the div.MuiBox-root.css-1ykdma4
    try:
        # Prefer strict selector that matches both class tokens from your sample HTML
        stay_xpath_strict = "//div[contains(@class,'MuiBox-root') and contains(@class,'css-1ykdma4')]//button[@data-log-id='stay-signed-in']"
        stay = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, stay_xpath_strict)))
        print("[*] 'Stay signed in' found (strict). Clicking.")
        safe_action_click(driver, stay)
        human_delay(0.6, 1.0)
        return True
    except TimeoutException:
        print("[*] 'Stay signed in' not found with strict selector immediately after load.")
    except Exception as e:
        print(f"[WARN] Error while checking strict 'Stay signed in' selector: {e}")

    # If strict not found, try looser selector for any button with data-log-id
    try:
        stay = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-log-id='stay-signed-in']")))
        print("[*] 'Stay signed in' found (loose). Clicking.")
        safe_action_click(driver, stay)
        human_delay(0.6, 1.0)
        return True
    except TimeoutException:
        print("[*] 'Stay signed in' not present yet — will check captcha and possibly retry Sign in.")
    except Exception as e:
        print(f"[WARN] Error while checking loose 'Stay signed in' selector: {e}")

    # If Stay not present, check for recaptcha and attempt solver (same as after Next)
    try:
        captcha_found, solver_clicked = handle_recaptcha_and_click_solver(driver)
    except Exception as e:
        print(f"[WARN] Exception while scanning for captcha after Sign in: {e}")
        captcha_found, solver_clicked = False, False

    if captcha_found and solver_clicked:
        print(f"[*] Solver clicked after Sign in -> waiting {AFTER_SOLVER_WAIT}s then attempting Sign in again.")
        time.sleep(AFTER_SOLVER_WAIT)
        # attempt to click Sign in again a few times
        re_click_ok = False
        for attempt in range(2):
            try:
                signin = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='test-button-signin']")))
                print(f"[*] Re-clicking Sign in (attempt {attempt+1}).")
                safe_action_click(driver, signin)
                human_delay(0.8, 1.2)
                re_click_ok = True
                break
            except Exception:
                human_delay(0.6, 1.0)
        if not re_click_ok:
            print("[ERROR] Could not click Sign in after solver.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "signin_after_solver_fail.png")
            return False
    elif captcha_found and not solver_clicked:
        print("[WARN] Captcha present after Sign in but solver click did not succeed; will try to re-click Sign in anyway.")
        try:
            signin = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='test-button-signin']")))
            safe_action_click(driver, signin)
            human_delay(0.8, 1.2)
        except Exception:
            print("[ERROR] Could not click Sign in after failed solver attempt.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "signin_after_solver_failed_and_click_failed.png")
            return False
    else:
        print("[*] No captcha found after Sign in; waiting a bit for 'Stay signed in' to appear.")

    # After solver & re-click, wait for page to become ready again then require Stay signed in to be present
    print("[*] Waiting for page to load after Sign in (post-captcha/retry)...")
    wait_for_page_ready(driver, timeout=12)

    try:
        # final strict attempt
        stay = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'MuiBox-root') and contains(@class,'css-1ykdma4')]//button[@data-log-id='stay-signed-in']")))
        print("[*] 'Stay signed in' found (final strict). Clicking.")
        safe_action_click(driver, stay)
        human_delay(0.6, 1.0)
        return True
    except Exception:
        try:
            stay = WebDriverWait(driver, DEFAULT_WAIT_SECONDS).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-log-id='stay-signed-in']")))
            print("[*] 'Stay signed in' found (final loose). Clicking.")
            safe_action_click(driver, stay)
            human_delay(0.6, 1.0)
            return True
        except Exception:
            print("[ERROR] 'Stay signed in' button not found after handling captcha and retries. This step is important and was not completed.")
            if SCREENSHOT_ON_ERROR:
                take_screenshot(driver, "stay_signed_in_not_found.png")
            return False

# ---------- High level flow with refresh-restart support ----------
def attempt_login_flow(driver, email, refresh_retries=REFRESH_RESTARTS):
    """
    Attempts entire login flow once. If solver clicked and Next cannot be found,
    refreshes and restarts (recursively) up to refresh_retries times.
    """
    # 1) Click sign in
    if not click_sign_in_button(driver):
        print("[ERROR] Could not click Sign in.")
        if SCREENSHOT_ON_ERROR:
            take_screenshot(driver, "signin_click_error.png")
        return False

    human_delay(0.8, 1.4)

    # 2) Fill account & Next
    if not fill_account_and_remember_then_next(driver, email):
        print("[ERROR] Failed to fill account / click Next.")
        if SCREENSHOT_ON_ERROR:
            take_screenshot(driver, "account_next_fail.png")
        return False

    # 3) Quick check for password
    short_deadline = time.time() + 3.5
    password_visible = False
    while time.time() < short_deadline:
        try:
            if driver.find_elements(By.ID, "password"):
                password_visible = True
                break
        except Exception:
            pass
        time.sleep(0.35)

    if password_visible:
        print("[*] Password field visible immediately after Next.")
        return fill_password_and_signin(driver)

    # 4) Password didn't appear -> try recaptcha + solver (simplified)
    captcha_found, solver_clicked = handle_recaptcha_and_click_solver(driver)

    if solver_clicked:
        print(f"[*] Solver clicked -> waiting {AFTER_SOLVER_WAIT}s then attempting Next.")
        time.sleep(AFTER_SOLVER_WAIT)
        clicked_next = click_next_button(driver)
        if not clicked_next:
            print("[WARN] Next button not found after solver click.")
            if refresh_retries > 0:
                print(f"[*] Refreshing page and restarting flow (remaining retries: {refresh_retries - 1})")
                try:
                    driver.refresh()
                    human_delay(1.5, 3.0)
                except Exception as e:
                    print(f"[WARN] refresh failed: {e}")
                # optional: try close cookie again after refresh
                try:
                    close_cookie_strict(driver, wait_seconds=2)
                except Exception:
                    pass
                return attempt_login_flow(driver, email, refresh_retries - 1)
            else:
                print("[ERROR] No refresh retries left; aborting.")
                if SCREENSHOT_ON_ERROR:
                    take_screenshot(driver, "next_not_found_after_solver.png")
                return False
        else:
            human_delay(0.4, 0.9)
    else:
        print("[*] Solver not clicked (or no recaptcha). Will try to ensure password field now.")

    # Ensure password field is visible (this will click Next again as fallback)
    if not ensure_password_field_visible_or_retry_next(driver):
        print("[ERROR] password field not visible after Next/captcha handling.")
        if SCREENSHOT_ON_ERROR:
            take_screenshot(driver, "password_not_visible.png")
        return False

    # Fill password & sign in
    if not fill_password_and_signin(driver):
        print("[ERROR] Could not complete password/signin step.")
        if SCREENSHOT_ON_ERROR:
            take_screenshot(driver, "password_signin_fail.png")
        return False

    return True

# ---------- Main ----------
def main():
    print("=== Samsung login (solver -> wait -> robust Next -> refresh+restart on Next-miss) ===")
    spot = input("Enter spot id (e.g. 1): ").strip()
    profile_id = input("Enter profile id (e.g. 1): ").strip()
    email = input("Enter email to use: ").strip()

    BASE_USER_DATA_DIR = rf"C:\smsng_spot{spot}"
    PROFILE_FOLDER = f"profile{profile_id}"
    os.makedirs(BASE_USER_DATA_DIR, exist_ok=True)

    print("\nUsing:")
    print(f"  BASE_USER_DATA_DIR = {BASE_USER_DATA_DIR}")
    print(f"  PROFILE_FOLDER     = {PROFILE_FOLDER}")
    print(f"  EMAIL              = {email}")
    print(f"  FIXED_PASSWORD     = {FIXED_PASSWORD}\n")

    opts = uc.ChromeOptions()
    opts.add_argument(f"--user-data-dir={BASE_USER_DATA_DIR}")
    opts.add_argument(f"--profile-directory={PROFILE_FOLDER}")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    chrome_bin = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin
        print(f"[+] Using Chrome binary: {chrome_bin}")

    driver = uc.Chrome(options=opts, version_main=CHROME_MAJOR_VERSION, headless=False)
    try:
        driver.get(SAMSUNG_INTRO_URL)
        driver.implicitly_wait(1)
        human_delay(0.6, 1.2)

        # optional cookie close
        if close_cookie_strict(driver, wait_seconds=3):
            print("[+] Cookie/footer close clicked.")
        else:
            print("[*] No strict cookie-close detected; continuing.")

        ok = attempt_login_flow(driver, email, refresh_retries=REFRESH_RESTARTS)
        if ok:
            print("\n[+] Login flow completed (attempted).")
        else:
            print("\n[!] Login flow failed (see logs).")

        time.sleep(4)
        input("Press ENTER to close browser and quit...")

    except Exception as e:
        print(f"[ERROR] Unexpected exception in main: {e}")
        if SCREENSHOT_ON_ERROR:
            try:
                take_screenshot(driver, "unexpected_main_error.png")
            except Exception:
                pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
