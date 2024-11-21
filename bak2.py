from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from datetime import datetime
import time
import logging
import os
import random
import signal
import sys
import atexit

logging.getLogger('selenium').setLevel(logging.ERROR)

class TwitterMonitor:
    def __init__(self, username):
        self.username = username
        self.seen_tweets = set()
        self.profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twitter_bot_profile")
        self.driver = None
        self.is_running = True
        self.last_refresh_time = time.time()
        atexit.register(self.cleanup)

    def setup_driver(self, headless=True):
        options = webdriver.ChromeOptions()
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        if headless:
            options.add_argument('--headless=new')
        options.add_argument(f'user-data-dir={self.profile_dir}')
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        if self.driver is not None:
            self.driver.quit()
        
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10, poll_frequency=1,
                                ignored_exceptions=[StaleElementReferenceException])

    def signal_handler(self, signum, frame):
        print("\n\nReceived signal to terminate. Cleaning up...")
        self.is_running = False
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        print("\nCleaning up resources...")
        try:
            if self.driver is not None:
                self.driver.quit()
                self.driver = None
                print("Browser closed successfully.")
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            try:
                os.system("taskkill /f /im chromedriver.exe >nul 2>&1")
            except:
                pass

    def check_login_status(self):
        try:
            self.driver.get("https://twitter.com/home")
            time.sleep(5)
            
            if "login" in self.driver.current_url.lower() or "i/flow" in self.driver.current_url.lower():
                return False
                
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='SideNav_AccountSwitcher_Button']")))
                return True
            except:
                return False
        except:
            return False

    def wait_for_manual_login(self):
        self.setup_driver(headless=False)
        
        if not self.check_login_status():
            print("\nNot logged in. Opening login page...")
            self.driver.get("https://twitter.com/i/flow/login")
            time.sleep(2)
            print("\nPlease login to Twitter manually in the browser window.")
            print("After logging in, press Enter to continue...")
            input()
            
            if self.check_login_status():
                print("Login successful! Session saved for next time.")
                self.setup_driver(headless=True)
            else:
                print("Login seems to have failed. Please try again.")
                self.wait_for_manual_login()
        else:
            print("Using saved login session...")
            self.setup_driver(headless=True)

    def wait_for_tweet_load(self):
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='tweet']")))
            time.sleep(2)
            return True
        except TimeoutException:
            print("Timeout waiting for tweets to load")
            return False

    def is_pinned_tweet(self, tweet_element):
        try:
            pinned = tweet_element.find_elements(By.CSS_SELECTOR, "[data-testid='socialContext']")
            return len(pinned) > 0 and "Pinned" in pinned[0].text
        except:
            return False

    def get_tweet_info(self, tweet_element):
        try:
            # Try to find the actual tweet text
            tweet_text = None
            try:
                tweets_text_elements = tweet_element.find_elements(By.CSS_SELECTOR, "[data-testid='tweetText']")
                if tweets_text_elements:
                    tweet_text = tweets_text_elements[-1].text
            except NoSuchElementException:
                return None, None, None

            if not tweet_text:
                return None, None, None

            # Get tweet link and original tweet author
            try:
                time_element = tweet_element.find_element(By.CSS_SELECTOR, "time")
                tweet_link = time_element.find_element(By.XPATH, "..").get_attribute("href")
                original_author = tweet_link.split('/')[3] if tweet_link else None
            except NoSuchElementException:
                tweet_link = None
                original_author = None

            # Determine if it's a reply and to whom
            try:
                reply_context = tweet_element.find_element(By.CSS_SELECTOR, "[data-testid='socialContext']")
                if "Replying to" in reply_context.text and original_author:
                    if original_author.lower() != self.username.lower():
                        tweet_type = f"[Reply to @{original_author}]"
                    else:
                        tweet_type = "[Self-Reply]"
                else:
                    tweet_type = "[Post]"
            except NoSuchElementException:
                tweet_type = "[Post]"

            return tweet_text, tweet_link, tweet_type

        except Exception as e:
            print(f"Error parsing tweet: {e}")
            return None, None, None

    def get_latest_tweets(self):
        if not self.wait_for_tweet_load():
            return []

        try:
            tweets = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='tweet']")
            if tweets:
                regular_tweets = [tweet for tweet in tweets if not self.is_pinned_tweet(tweet)]
                valid_tweets = []
                for tweet in regular_tweets[:3]:
                    tweet_info = self.get_tweet_info(tweet)
                    if tweet_info[0]:
                        valid_tweets.append(tweet_info)
                return valid_tweets
            return []
        except Exception as e:
            print(f"Error getting tweets: {e}")
            return []

    def monitor(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        print("\nMonitoring started!")
        print("Press Ctrl+C to stop safely")
        print("-" * 50)

        self.wait_for_manual_login()

        print(f"\nStarting to monitor @{self.username} (posts and replies)")
        self.driver.get(f"https://twitter.com/{self.username}/with_replies")
        
        if not self.wait_for_tweet_load():
            print("Initial load failed")
            return

        initial_tweets = self.get_latest_tweets()
        print(f"Monitoring started. Waiting for new tweets or replies...")
        self.last_refresh_time = time.time()

        while self.is_running:
            try:
                current_time = time.time()
                elapsed_time = current_time - self.last_refresh_time

                if elapsed_time >= 15 + random.uniform(0, 5):
                    print(f"\nRefreshing page... (Last refresh: {int(elapsed_time)} seconds ago)")
                    self.driver.get(f"https://twitter.com/{self.username}/with_replies")
                    if not self.wait_for_tweet_load():
                        continue
                    self.last_refresh_time = time.time()
                
                new_tweets = self.get_latest_tweets()
                
                for tweet_text, tweet_link, tweet_type in new_tweets:
                    if tweet_text not in self.seen_tweets:
                        print(f"\nNew {tweet_type} detected at {datetime.now()}:")
                        print(f"@{self.username}: {tweet_text}")
                        if tweet_link:
                            print(f"Link: \033[34m\033[4m{tweet_link}\033[0m")
                        print("-" * 50)
                        self.seen_tweets.add(tweet_text)
                
                time.sleep(1)
                
            except Exception as e:
                print(f"Error in monitor loop: {e}")
                time.sleep(5)
                self.last_refresh_time = time.time() - 25

def main():
    monitor = None
    try:
        username_to_monitor = "0xpeely"  # Change this to the username you want to monitor
        monitor = TwitterMonitor(username_to_monitor)
        monitor.monitor()
    except KeyboardInterrupt:
        print("\n\nReceived Ctrl+C. Cleaning up...")
    except Exception as e:
        print(f"\nError occurred: {e}")
    finally:
        if monitor:
            monitor.cleanup()
        print("Script terminated safely.")

if __name__ == "__main__":
    main()