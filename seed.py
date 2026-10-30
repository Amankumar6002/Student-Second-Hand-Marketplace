from app import create_app
from app.category_defaults import DEFAULT_CATEGORY_NAMES
from app.extensions import db
from app.models import Category, Product, ProductImage, User, AdminProduct

app = create_app()

with app.app_context():
    for name in DEFAULT_CATEGORY_NAMES:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
    admin = User.query.filter_by(university_email="admin@klu.ac.in").first()
    if not admin:
        admin = User(name="Marketplace Admin", registration_number="ADMIN-001", university_email="admin@klu.ac.in", department="Administration", section="A", role="admin", is_verified=True)
        admin.set_password("ChangeMe123!")
        db.session.add(admin)
    db.session.commit()
    demo_sellers = {}
    for name, registration_number in [("Arun Raj", "DEMO-001"), ("Siva Kumar", "DEMO-002"), ("Naveen Prakash", "DEMO-003"), ("Manoj Jay", "DEMO-004")]:
        email = f"{registration_number.lower()}@klu.ac.in"
        seller = User.query.filter_by(university_email=email).first()
        if not seller:
            seller = User(name=name, registration_number=registration_number, university_email=email, department="Computer Science", section="A", is_verified=True)
            seller.set_password("DemoUser123!")
            db.session.add(seller)
            db.session.flush()
        demo_sellers[name] = seller

    demo_products = [
        ("CASIO fx-991EX Scientific Calculator", "Calculators", "Naveen Prakash", 850, None, "sale", "Like new", "KLU Library", "https://images.unsplash.com/photo-1587145820266-a5951ee6f620?auto=format&fit=crop&w=800&q=80"),
        ("Arduino Uno Engineering Starter Kit", "Engineering Kits", "Arun Raj", 1250, None, "sale", "Good", "Boys Hostel Block A", "https://images.unsplash.com/photo-1553406830-ef2513450d76?auto=format&fit=crop&w=800&q=80"),
        ("Digital Multimeter and Wiring Kit", "Project Materials", "Siva Kumar", 90, 90, "both", "Good", "Innovation Lab", "https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=800&q=80"),
        ("Data Structures and Operating Systems Books", "Books", "Manoj Jay", 600, None, "sale", "Good", "Main Block", "https://images.unsplash.com/photo-1543002588-bfa74002ed7e?auto=format&fit=crop&w=800&q=80"),
        ("Electronics Project Soldering Station", "Electronics", "Arun Raj", 75, 75, "rent", "Good", "Girls Hostel Block B", "https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?auto=format&fit=crop&w=800&q=80"),
        ("Lenovo IdeaPad Slim 3 Laptop", "Electronics", "Siva Kumar", 23000, None, "sale", "Like new", "KLU Cafeteria", "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=800&q=80"),
        ("Single Mattress and Study Lamp Set", "Hostel Essentials", "Manoj Jay", 1800, None, "sale", "Good", "Boys Hostel Block C", "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?auto=format&fit=crop&w=800&q=80"),
        ("Hero Campus Bicycle", "Bicycles", "Naveen Prakash", 120, 120, "both", "Good", "North Gate Parking", "https://images.unsplash.com/photo-1485965120184-e220f721d03e?auto=format&fit=crop&w=800&q=80"),
        ("KLU Tech Club Hoodie", "Clothing", "Siva Kumar", 450, None, "sale", "Like new", "Main Block", "https://images.unsplash.com/photo-1556821840-3a63f95609a7?auto=format&fit=crop&w=800&q=80"),
        ("Yonex Badminton Racket", "Sports Equipment", "Arun Raj", 60, 60, "rent", "Good", "Indoor Stadium", "https://images.unsplash.com/photo-1626224583764-f87db24ac4ea?auto=format&fit=crop&w=800&q=80"),
    ]
    for title, category_name, seller_name, price, rental_price, listing_type, condition, location, image_url in demo_products:
        if Product.query.filter_by(title=title).first():
            continue
        category = Category.query.filter_by(name=category_name).first()
        product = Product(seller_id=demo_sellers[seller_name].id, category_id=category.id, title=title, description=f"Well-maintained {title.lower()} available for KLU students.", price=price, rental_price=rental_price, listing_type=listing_type, condition=condition, location=location, availability="Available now", status="available", approval_status="approved")
        db.session.add(product)
        db.session.flush()
        db.session.add(ProductImage(product_id=product.id, image_path=image_url))
    db.session.commit()

    # Seed Admin Store Products
    if AdminProduct.query.count() == 0:
        admin_products = [
            ("KLU Official College T-Shirt", "Apparel", "Premium quality 100% cotton white T-shirt with embroidered KLU logo. Perfect for college events and casual wear.", 299.00, 50),
            ("KLU Hoodie - Burgundy", "Apparel", "Warm and comfortable hoodie in college burgundy color with front logo print. Ideal for winter season.", 599.00, 35),
            ("Lab Coat - White", "Academic", "Professional white lab coat for science lab work. Durable material with multiple pockets.", 499.00, 60),
            ("Premium Stationery Kit", "Stationery", "Complete stationery set with notebooks, pens, pencils, rulers, erasers, and sharpeners. Everything a student needs!", 349.00, 75),
            ("Laptop Backpack - Black", "Accessories", "Spacious black backpack with dedicated laptop compartment (up to 17 inches), water-resistant material, and ergonomic design.", 799.00, 45),
            ("Stainless Steel Water Bottle (1L)", "Accessories", "Double-walled insulated water bottle keeps drinks hot for 12 hours or cold for 24 hours. Eco-friendly and durable.", 449.00, 80),
            ("College ID Card Holder", "Accessories", "Leather ID card holder with KLU branding. Compact size perfect for carrying in pocket or on keychain.", 99.00, 120),
            ("Scientific Calculator", "Academic", "Advanced scientific calculator with 240+ functions. Essential for engineering, maths, and science students.", 599.00, 40),
            ("Notebook Bundle (5 Books)", "Stationery", "Set of 5 high-quality notebooks with 200 pages each. Perfect for different subjects and note-taking.", 199.00, 100),
            ("USB Drive 32GB", "Electronics", "High-speed USB 3.0 flash drive with 32GB capacity. Reliable for storing assignments and projects.", 349.00, 55),
            ("Bluetooth Wireless Earbuds", "Electronics", "Premium wireless earbuds with active noise cancellation, 30-hour battery life, and crystal clear sound quality.", 1499.00, 25),
            ("Desk Lamp - LED", "Accessories", "Energy-efficient LED desk lamp with adjustable brightness and color temperature. Perfect for study room.", 699.00, 30),
            ("Portable Phone Charger 20000mAh", "Electronics", "Fast-charging power bank with 20000mAh capacity. Can charge 2 phones simultaneously. Compact and lightweight.", 799.00, 50),
            ("Study Table Organizer", "Accessories", "Wooden desk organizer with multiple compartments for pens, papers, and stationery items. Minimalist design.", 249.00, 65),
            ("Mathematical Set - Premium", "Academic", "Complete mathematical set with compass, ruler, set square, protractor, and pencil. Essential for engineering drawing.", 149.00, 90),
            ("College Tote Bag", "Accessories", "Spacious canvas tote bag with college logo. Perfect for carrying books, laptop, and daily essentials.", 249.00, 75),
            ("Webcam HD 1080P", "Electronics", "Crystal clear HD webcam for online classes and video conferencing. Built-in microphone and auto-focus.", 999.00, 35),
            ("Desk Organizer Drawers", "Accessories", "3-tier drawer organizer with transparent drawers for easy visibility. Perfect for keeping stationery organized.", 399.00, 50),
            ("Ring Light with Stand", "Electronics", "18-inch LED ring light perfect for video calls, online classes, and content creation. Includes tripod stand.", 1299.00, 20),
            ("College Merch Bundle", "Apparel", "Exclusive bundle with T-shirt, pen set, notebook, ID holder, and water bottle. Best value for new students!", 1499.00, 40),
        ]
        
        for title, category, description, price, stock in admin_products:
            product = AdminProduct(
                title=title,
                description=description,
                category=category,
                price=price,
                stock=stock,
                status="available"
            )
            db.session.add(product)
        
        db.session.commit()
        print(f"✅ Seeded {len(admin_products)} KLU Store products!")
    print("Seed complete. Development admin: admin@klu.ac.in / ChangeMe123!")
