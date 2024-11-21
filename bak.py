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

logging.getLogger('selenium').setLevel(logging.ERROR)

class TwitterMonitor:
    def __init__(self, username):
        self.username = username
        self.seen_tweets = set()
        self.profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "twitter_bot_profile")
        self.setup_driver()
        self.last_refresh_time = time.time()
        self.is_running = True

    def setup_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--log-level=3')
        options.add_argument('--silent')
        options.add_argument(f'user-data-dir={self.profile_dir}')
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10, poll_frequency=1,
                                ignored_exceptions=[StaleElementReferenceException])

    def signal_handler(self, signum, frame):
        print("\n\nReceived signal to terminate. Cleaning up...")
        self.is_running = False
        self.cleanup()
        print("Cleanup complete. Exiting safely.")
        sys.exit(0)

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
        if not self.check_login_status():
            print("\nNot logged in. Opening login page...")
            self.driver.get("https://twitter.com/i/flow/login")
            time.sleep(2)
            print("\nPlease login to Twitter manually in the browser window.")
            print("After logging in, press Enter to continue...")
            input()
            
            if self.check_login_status():
                print("Login successful! Session saved for next time.")
            else:
                print("Login seems to have failed. Please try again.")
                self.wait_for_manual_login()
        else:
            print("Using saved login session...")

    def is_pinned_tweet(self, tweet_element):
        try:
            pinned = tweet_element.find_elements(By.CSS_SELECTOR, "[data-testid='socialContext']")
            return len(pinned) > 0 and "Pinned" in pinned[0].text
        except:
            return False

    def wait_for_tweet_load(self):
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='tweet']")))
            time.sleep(2)
            return True
        except TimeoutException:
            print("Timeout waiting for tweets to load")
            return False

    def get_tweet_info(self, tweet_element):
        try:
            tweet_text = None
            retry_count = 0
            while retry_count < 3:
                try:
                    tweet_text = tweet_element.find_element(By.CSS_SELECTOR, "[data-testid='tweetText']").text
                    break
                except NoSuchElementException:
                    retry_count += 1
                    time.sleep(1)
            
            if tweet_text is None:
                return None, None

            try:
                time_element = tweet_element.find_element(By.CSS_SELECTOR, "time")
                tweet_link = time_element.find_element(By.XPATH, "..").get_attribute("href")
            except NoSuchElementException:
                tweet_link = None

            try:
                reply_context = tweet_element.find_element(By.CSS_SELECTOR, "[data-testid='socialContext']").text
                if "Replying to" in reply_context:
                    tweet_text = f"[Reply] {tweet_text}"
            except NoSuchElementException:
                pass
            
            return tweet_text, tweet_link
        except Exception as e:
            return None, None

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
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        print("\nMonitoring started!")
        print("Press Ctrl+C to stop safely")
        print("-" * 50)

        self.wait_for_manual_login()

        print(f"Starting to monitor @{self.username}")
        self.driver.get(f"https://twitter.com/{self.username}")
        
        if not self.wait_for_tweet_load():
            print("Initial load failed")
            return

        initial_tweets = self.get_latest_tweets()
        print(f"Monitoring started. Waiting for new tweets...")
        self.last_refresh_time = time.time()

        while self.is_running:
            try:
                current_time = time.time()
                elapsed_time = current_time - self.last_refresh_time

                if elapsed_time >= 15 + random.uniform(0, 5):
                    print(f"\nRefreshing page... (Last refresh: {int(elapsed_time)} seconds ago)")
                    self.driver.refresh()
                    if not self.wait_for_tweet_load():
                        continue
                    self.last_refresh_time = time.time()
                
                new_tweets = self.get_latest_tweets()
                
                for tweet_text, tweet_link in new_tweets:
                    if tweet_text not in self.seen_tweets:
                        print(f"\nNew tweet detected at {datetime.now()}:")
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

    def cleanup(self):
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
                print("Browser closed successfully.")
        except Exception as e:
            print(f"Error during cleanup: {e}")

def main():
    username_to_monitor = "Niklaus1911"  # Change this to the username you want to monitor
    monitor = TwitterMonitor(username_to_monitor)
    
    try:
        monitor.monitor()
    except KeyboardInterrupt:
        print("\n\nReceived Ctrl+C. Cleaning up...")
    except Exception as e:
        print(f"\nError occurred: {e}")
    finally:
        monitor.cleanup()
        print("Script terminated safely.")

if __name__ == "__main__":
    main()