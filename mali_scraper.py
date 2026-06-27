import requests
from bs4 import BeautifulSoup


def find_mali_mali_deals():
    # 1. The website we are "visiting" (Using a safe test site for now)
    url = "http://books.toscrape.com/"

    # 2. Tell the website we are a real person using a Mac, not a robot
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print("🔍 Mali Mali is searching for treasures...")

    # 3. Send the request to the website
    response = requests.get(url, headers=headers)

    # 4. Check if the connection was successful (Status 200 means OK)
    if response.status_code == 200:
        # 5. Read the HTML code of the page
        soup = BeautifulSoup(response.text, 'html.parser')

        # 6. Find all the products on the page
        # (On this test site, every product is inside an <article> tag with the class 'product_pod')
        products = soup.find_all('article', class_='product_pod')

        print(f"✅ Found {len(products)} items! Here are the top treasures:\n")

        # 7. Loop through the first 3 products and extract the details
        for product in products[:3]:
            # Get the name of the product
            title = product.h3.a['title']

            # Get the price
            price = product.find('p', class_='price_color').text

            # Print it out beautifully
            print(f"🛍️  Item: {title}")
            print(f"💰 Price: {price}")
            print("-" * 40)

    else:
        print(f"❌ Oops! The website blocked us. Status code: {response.status_code}")


# This tells Python to run the function when we execute the file
if __name__ == "__main__":
    find_mali_mali_deals()