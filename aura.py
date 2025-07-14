import requests
import argparse
import logging
import sys
import os
import json  # Added for caching
from datetime import datetime, timedelta
from dotenv import load_dotenv  # Added for .env loading

# Load .env file from the script's directory
load_dotenv()
if os.path.exists(".env"):
    logging.info("Loaded configuration from .env file.")
else:
    logging.info(".env file not found; using system environment variables or CLI args.")

# Configure logging to output to stdout by default
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

REPORT_WIDTH = 80  


def format_price(price: float, max_decimals: int = 4) -> str:
    """
    Formats a float price, trimming trailing zeros and decimal point if unnecessary.
    e.g., 2.3300 -> '2.33', 2.0000 -> '2', 2.2633 -> '2.2633'
    """
    formatted = f"{price:.{max_decimals}f}"
    formatted = formatted.rstrip("0").rstrip(".") if "." in formatted else formatted
    return formatted


def fetch_prices(date_str: str, cache_dir: str = ".cache"):
    
    cache_file = os.path.join(
        cache_dir, f"prices_{date_str.replace('/', '')}.json"
    )
    os.makedirs(cache_dir, exist_ok=True)

    # Check cache first
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                logging.info(f"Loading cached prices for {date_str}")
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Cache read error for {date_str}: {e}. Fetching fresh.")

    base_url = "https://www.aura.dk/api/hour-price/data"
    content_ref = "40291"
    url = f"{base_url}?date={date_str}&currentBlockContentReference={content_ref}"

    try:
        logging.info(f"Fetching prices for {date_str} ...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:  # Streamlined exception handling
        logging.error(f"Error fetching data for {date_str}: {e}")
        return None
    except ValueError as e:
        logging.error(f"Failed to parse JSON: {e}")
        return None

    chart_series = data.get("chartSeries")
    if not chart_series or not isinstance(chart_series, list):
        logging.error("No valid 'chartSeries' data found.")
        return None

    hourly_totals = {}
    for hour_idx in range(24):
        hour_str = f"{hour_idx:02d}"
        total = 0.0
        found = False
        for series in chart_series:
            for tp in series.get("timePoints", []):
                if tp.get("name") == hour_str:
                    price = tp.get("priceWestDenmark")
                    if price is not None:
                        try:
                            total += float(price)
                            found = True
                        except ValueError:
                            logging.warning(
                                f"Skipping invalid price '{price}' for {hour_str}."
                            )
        if found:
            hourly_totals[hour_str] = round(total, 4)
        else:
            logging.warning(f"No price data for {hour_str} on {date_str}.")

    if not hourly_totals:
        return None

    # Cache the result
    try:
        with open(cache_file, "w") as f:
            json.dump(hourly_totals, f)
        logging.info(f"Cached prices for {date_str}")
    except IOError as e:
        logging.warning(f"Cache write error: {e}")

    return hourly_totals


def _format_hour_ranges(hours: list[str]) -> str:
   
    if not hours:
        return ""

    hour_ints = sorted(int(h) for h in hours)
    ranges = []
    start = hour_ints[0]
    end = start
    for i in range(1, len(hour_ints)):
        if hour_ints[i] == end + 1:
            end = hour_ints[i]
        else:
            ranges.append(
                f"{start:02d}:00"
                if start == end
                else f"{start:02d}:00-{(end + 1) % 24:02d}:00"
            )
            start = end = hour_ints[i]
    ranges.append(
        f"{start:02d}:00" if start == end else f"{start:02d}:00-{(end + 1) % 24:02d}:00"
    )
    return ", ".join(ranges)


def _ascii_sparkline(prices: list[float], width: int = 20) -> str:
    """Simple ASCII sparkline for price trends (e.g., ▁▂▄▆█)."""
    prices = [p for p in prices if p is not None]  # Filter None
    if not prices:
        return ""
    min_p, max_p = min(prices), max(prices)
    scale = lambda p: int((p - min_p) / (max_p - min_p) * 7) if max_p > min_p else 0
    bars = "▁▂▃▄▅▆▇█"
    return "".join(bars[scale(p)] for p in prices)


def format_prices_for_display(
    prices: dict, date_str: str, sort_by: str = None
) -> str:
    """
    Formats hourly prices with summary and optional sorting.
    Added ASCII sparkline for visual trend overview.
    """
    if not prices:
        return f"No price data for {date_str}."

    output_lines = []
    output_lines.append(
        f" HOURLY POWER PRICES (DK1) - {date_str} "
    )

    values = list(prices.values())
    avg_price = sum(values) / len(values)
    min_price = min(values)
    max_price = max(values)

    cheapest = [h for h, p in prices.items() if abs(p - min_price) < 0.00001]
    expensive = [h for h, p in prices.items() if abs(p - max_price) < 0.00001]

    output_lines.append(f"Average Price: {format_price(avg_price)} DKK/kWh")
    output_lines.append(
        f"Cheapest: {_format_hour_ranges(cheapest)} ({format_price(min_price)} DKK/kWh)"
    )
    output_lines.append(
        f"Most Expensive: {_format_hour_ranges(expensive)} ({format_price(max_price)} DKK/kWh)"
    )
    output_lines.append(f"Trend Sparkline: {_ascii_sparkline(values)}")

    # Sort hours if requested (e.g., by price or hour)
    keys = sorted(prices)
    if sort_by == "price":
        keys = sorted(prices, key=prices.get)
    elif sort_by == "price_desc":
        keys = sorted(prices, key=prices.get, reverse=True)

    for hour_str in keys:
        next_hour = f"{(int(hour_str) + 1) % 24:02d}"
        output_lines.append(
            f"{hour_str}:00 - {next_hour}:00 | {format_price(prices[hour_str])} DKK/kWh"
        )
    return "\n".join(output_lines)


def format_comparison_for_display(
    today_prices: dict,
    today_date_str: str,
    yesterday_prices: dict,
    yesterday_date_str: str,
    sort_by: str = None,
) -> str:
    """
    Enhanced comparison with percentage change and optional sorting by diff.
    Swapped columns for yesterday-first as before, added % change for optimality.
    """
    if not today_prices or not yesterday_prices:
        return ""

    comparison_lines = []
    comparison_lines.append(
        f" PRICE COMPARISON ({today_date_str} vs {yesterday_date_str}) "
    )

    diffs = []
    up, down, stable = 0, 0, 0
    for hour in range(24):
        h = f"{hour:02d}"
        if h in today_prices and h in yesterday_prices:
            diff = today_prices[h] - yesterday_prices[h]
            diffs.append((h, diff))
            if diff > 0.0001:
                up += 1
            elif diff < -0.0001:
                down += 1
            else:
                stable += 1

    if diffs:
        avg_diff = sum(d[1] for d in diffs) / len(diffs)
        comparison_lines.append(f"Avg Change: {format_price(avg_diff)} DKK/kWh")
        comparison_lines.append(f"Increased: {up} | Decreased: {down} | Stable: {stable}")
        comparison_lines.append(
            f"Trend Sparkline (Diffs): {_ascii_sparkline([d[1] for d in diffs])}"
        )
    comparison_lines.append(
        "{:<11} | {:<8} | {:<8} | {:<8} | {:<8} | {:<5}".format(
            "Hour", "Yest", "Today", "Change", "% Chg", "Trend"
        )
    )

    # Sort by diff if requested
    if sort_by == "diff":
        diffs.sort(key=lambda x: x[1])
    elif sort_by == "diff_desc":
        diffs.sort(key=lambda x: x[1], reverse=True)

    for hour_str, diff in diffs:
        yest = yesterday_prices[hour_str]
        today = today_prices[hour_str]
        pct_chg = (diff / yest * 100) if yest != 0 else None  # Handle div by zero
        if pct_chg is not None:
            pct_chg_formatted = f"{format_price(pct_chg, 2)}%"
        else:
            pct_chg_formatted = "N/A"
        trend = "▲" if diff > 0.0001 else "▼" if diff < -0.0001 else "●"
        next_hour = f"{(int(hour_str) + 1) % 24:02d}"
        comparison_lines.append(
            "{:<11} | {:<8} | {:<8} | {:<8} | {:<8} | {:<5}".format(
                f"{hour_str}:00-{next_hour}:00",
                format_price(yest),
                format_price(today),
                format_price(diff) if diff >= 0 else f"-{format_price(abs(diff))}",
                pct_chg_formatted,
                trend,
            )
        )
    return "\n".join(comparison_lines)


def save_output_to_file(output_content: str, date_str: str, output_dir: str):
    # Unchanged, but added encoding check
    try:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"prices_{date_str.replace('/', '')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(output_content + "\n")
        logging.info(f"Saved to {path}")
    except OSError as e:
        logging.error(f"File save error: {e}")


def send_telegram_message(message: str, bot_token: str, chat_id: str):
    # Unchanged, but streamlined logging
    if not bot_token or not chat_id:
        logging.error("Missing Telegram token or chat ID.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        if response.json().get("ok"):
            logging.info("Telegram message sent.")
        else:
            logging.error("Telegram send failed.")
    except requests.RequestException as e:
        logging.error(f"Telegram error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch and display hourly power prices for West Denmark from AURA API."
    )
    parser.add_argument(
        "-d", "--date", help="Date (YYYY/MM/DD). Defaults to today."
    )
    parser.add_argument(
        "-o", "--output-dir", help="Save output to directory."
    )
    parser.add_argument(
        "--compare-yesterday",
        action="store_true",
        help="Compare with yesterday (default: off).",
    )
    parser.add_argument(
        "--sort-by",
        choices=["price", "price_desc", "diff", "diff_desc"],
        help="Sort display by price or diff (for comparison).",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send to Telegram (requires token and chat-id from .env, env vars, or CLI).",
    )
    parser.add_argument(
        "--telegram-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token (overrides .env or system env).",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID"),
        help="Telegram chat ID (overrides .env or system env).",
    )
    args = parser.parse_args()

    today_dt = (
        datetime.strptime(args.date, "%Y/%m/%d")
        if args.date
        else datetime.now()
    )
    today_str = today_dt.strftime("%Y/%m/%d")
    yesterday_dt = today_dt - timedelta(days=1)
    yesterday_str = yesterday_dt.strftime("%Y/%m/%d")

    today_prices = fetch_prices(today_str)
    if not today_prices:
        logging.error(f"Failed to fetch {today_str}. Aborting.")
        sys.exit(1)

    yesterday_prices = None
    if args.compare_yesterday:
        yesterday_prices = fetch_prices(yesterday_str)

    full_output = [format_prices_for_display(today_prices, today_str, args.sort_by)]
    if args.compare_yesterday and yesterday_prices:
        comp = format_comparison_for_display(
            today_prices, today_str, yesterday_prices, yesterday_str, args.sort_by
        )
        full_output.append("\n\n" + comp)

    output_str = "".join(full_output)
    print(output_str)

    if args.output_dir:
        save_output_to_file(output_str, today_str, args.output_dir)

    if args.send_telegram and args.telegram_token and args.telegram_chat_id:
        send_telegram_message(output_str, args.telegram_token, args.telegram_chat_id)
    elif args.send_telegram:
        logging.warning("Missing Telegram config. Skipping.")
