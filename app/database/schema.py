DATABASE_SCHEMA = """
DATABASE: bizpilot
DIALECT: PostgreSQL

TABLE: customers
- customer_id VARCHAR PRIMARY KEY
- customer_unique_id VARCHAR
- customer_zip_code_prefix VARCHAR
- customer_city VARCHAR
- customer_state VARCHAR

TABLE: orders
- order_id VARCHAR PRIMARY KEY
- customer_id VARCHAR
- order_status VARCHAR
- order_purchase_timestamp TIMESTAMP
- order_approved_at TIMESTAMP
- order_delivered_carrier_date TIMESTAMP
- order_delivered_customer_date TIMESTAMP
- order_estimated_delivery_date TIMESTAMP

TABLE: order_items
- order_id VARCHAR
- order_item_id INTEGER
- product_id VARCHAR
- seller_id VARCHAR
- shipping_limit_date TIMESTAMP
- price NUMERIC
- freight_value NUMERIC

TABLE: order_payments
- order_id VARCHAR
- payment_sequential INTEGER
- payment_type VARCHAR
- payment_installments INTEGER
- payment_value NUMERIC

TABLE: order_reviews
- review_id VARCHAR
- order_id VARCHAR
- review_score INTEGER
- review_comment_title TEXT
- review_comment_message TEXT
- review_creation_date TIMESTAMP
- review_answer_timestamp TIMESTAMP

TABLE: products
- product_id VARCHAR PRIMARY KEY
- product_category_name VARCHAR
- product_name_lenght INTEGER
- product_description_lenght INTEGER
- product_photos_qty INTEGER
- product_weight_g NUMERIC
- product_length_cm NUMERIC
- product_height_cm NUMERIC
- product_width_cm NUMERIC

TABLE: sellers
- seller_id VARCHAR PRIMARY KEY
- seller_city VARCHAR
- seller_state VARCHAR

TABLE: geolocation
- geolocation_zip_code_prefix VARCHAR
- geolocation_lat NUMERIC
- geolocation_lng NUMERIC
- geolocation_city VARCHAR
- geolocation_state VARCHAR

TABLE: product_category_name_translation
- product_category_name VARCHAR PRIMARY KEY
- product_category_name_english VARCHAR

RELATIONSHIPS:
- orders.customer_id = customers.customer_id
- order_items.order_id = orders.order_id
- order_items.product_id = products.product_id
- order_items.seller_id = sellers.seller_id
- order_payments.order_id = orders.order_id
- order_reviews.order_id = orders.order_id
- products.product_category_name =
  product_category_name_translation.product_category_name

BUSINESS RULES:
- Revenue from product sales = SUM(order_items.price).
- Freight is separate from product revenue.
- Delivered orders use orders.order_status = 'delivered'.
- Purchase date uses orders.order_purchase_timestamp.
- Delivery lateness compares actual delivery date
  against estimated delivery date.
- To connect orders with products, JOIN orders to
  order_items using order_id, then order_items to
  products using product_id.
- Never join orders directly to products.
- If a table has an alias, always use that alias
  when referencing its columns.
- Use the exact column names defined in this schema.
"""