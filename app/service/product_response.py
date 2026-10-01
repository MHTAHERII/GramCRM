import re


PRODUCT_TOKENS = re.compile(r"\{(product_name|price|stock|unit|description)\}")


def render_product_response(template: str, product=None) -> str:
    if product is None:
        return template
    values = {
        "product_name": product.name,
        "price": format(product.price, ","),
        "stock": str(product.stock),
        "unit": product.unit or "عدد",
        "description": product.description or "",
    }
    return PRODUCT_TOKENS.sub(lambda match: values[match.group(1)], template)


def keyword_response(keyword) -> str:
    return render_product_response(keyword.response, keyword.product)
