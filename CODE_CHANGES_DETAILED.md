# CODE CHANGES - BEFORE & AFTER

## File 1: app/products/routes.py - create() function

### BEFORE (Lines 95-115) - BROKEN CODE ❌
```python
@products_bp.route("/product/create", methods=["GET", "POST"])
@active_required
def create():
    if not current_user.is_verified:
        flash("Your account must be verified before you can list an item.", "warning")
        return redirect(url_for("products.home"))
    categories = Category.query.order_by(Category.name).all()
    if request.method == "POST":
        product = Product(seller_id=current_user.id, category_id=request.form.get("category_id"), title=request.form.get("title", "").strip(), description=request.form.get("description", "").strip(), price=request.form.get("price") or 0, rental_price=request.form.get("rental_price") or None, listing_type=request.form.get("listing_type"), condition=request.form.get("condition"), location=request.form.get("location", "").strip(), availability=request.form.get("availability", "").strip())
        if not product.title or not product.description or product.listing_type not in {"sale", "rent", "both"}:
            flash("Complete all required listing fields.", "danger")
        else:
            db.session.add(product)
            db.session.flush()
            _save_images(product)
            db.session.commit()
            flash("Listing submitted for admin approval.", "success")
            return redirect(url_for("products.detail", product_id=product.id))
    return render_template("products/form.html", categories=categories, product=None)
```

**Problems:**
- Line 3: `category_id=request.form.get("category_id")` → String passed, needs integer
- Line 3: `price=request.form.get("price") or 0` → String or 0, needs Decimal
- Line 3: `rental_price=request.form.get("rental_price") or None` → String or None, needs Decimal
- Line 3: `condition=request.form.get("condition")` → Could be None (form has no default)
- Line 4: `product.listing_type` checked but could be None
- Product object created BEFORE validation, then checked after
- Database insert attempted with invalid types → HTTP 400 error

### AFTER (Lines 95-199) - FIXED CODE ✅
```python
@products_bp.route("/product/create", methods=["GET", "POST"])
@active_required
def create():
    if not current_user.is_verified:
        flash("Your account must be verified before you can list an item.", "warning")
        return redirect(url_for("products.home"))
    categories = Category.query.order_by(Category.name).all()
    if request.method == "POST":
        # Extract and validate form data
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        listing_type = request.form.get("listing_type", "").strip()
        condition = request.form.get("condition", "").strip()
        location = request.form.get("location", "").strip()
        availability = request.form.get("availability", "").strip()
        
        # Validate required fields
        if not title:
            flash("Product name is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not description:
            flash("Description is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if listing_type not in {"sale", "rent", "both"}:
            flash("Please select a valid listing type (Sell, Rent, or Both).", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not condition:
            flash("Please select a condition.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        if not location:
            flash("Pickup location is required.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert category_id
        try:
            category_id = int(request.form.get("category_id", 0))
            if category_id <= 0:
                flash("Please select a category.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        except (ValueError, TypeError):
            flash("Please select a valid category.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert price
        try:
            price = request.form.get("price", "").strip()
            if not price:
                flash("Price is required.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
            price = Decimal(price)
            if price < 0:
                flash("Price cannot be negative.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        except (ValueError, TypeError, Exception):
            flash("Price must be a valid number.", "danger")
            return render_template("products/form.html", categories=categories, product=None)
        
        # Validate and convert rental_price if provided
        rental_price = None
        rental_price_str = request.form.get("rental_price", "").strip()
        if rental_price_str:
            try:
                rental_price = Decimal(rental_price_str)
                if rental_price < 0:
                    flash("Rental price cannot be negative.", "danger")
                    return render_template("products/form.html", categories=categories, product=None)
            except (ValueError, TypeError, Exception):
                flash("Rental price must be a valid number.", "danger")
                return render_template("products/form.html", categories=categories, product=None)
        
        # Create product with validated data
        product = Product(
            seller_id=current_user.id,
            category_id=category_id,
            title=title,
            description=description,
            price=price,
            rental_price=rental_price,
            listing_type=listing_type,
            condition=condition,
            location=location,
            availability=availability
        )
        
        try:
            db.session.add(product)
            db.session.flush()
            _save_images(product)
            db.session.commit()
            flash("Listing submitted for admin approval.", "success")
            return redirect(url_for("products.detail", product_id=product.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating listing: {str(e)}", "danger")
            return render_template("products/form.html", categories=categories, product=None)
    
    return render_template("products/form.html", categories=categories, product=None)
```

**Fixes:**
- All form data extracted and stripped first (lines 107-112)
- Required fields validated individually (lines 114-135)
- category_id explicitly converted to int (line 137-143)
- price explicitly converted to Decimal (line 145-155)
- rental_price explicitly converted to Decimal if provided (line 157-167)
- Product object only created AFTER all validation passes (line 169-180)
- Database commit wrapped in try-except (line 182-194)
- Specific error messages returned for each validation failure
- No more generic 400 errors

---

## File 2: app/templates/products/form.html

### BEFORE ❌
```html
<select name="condition">
    <option>Like New</option>
    <option>New</option>
    <option>Good</option>
    <option>Fair</option>
    <option>Used</option>
</select>

<select name="listing_type">
    <option value="sale">Sell</option>
    <option value="rent">Rent</option>
    <option value="both">Sell & rent</option>
</select>
```

**Problems:**
- No `required` attribute on condition select
- No `required` attribute on listing_type select
- No default/placeholder option in either select
- Condition options have no `value` attribute, so value becomes the text content
- If user doesn't explicitly select an option, empty string or None is sent to server

### AFTER ✅
```html
<select name="condition" required>
    <option value="">-- Select Condition --</option>
    <option value="Like New">Like New</option>
    <option value="New">New</option>
    <option value="Good">Good</option>
    <option value="Fair">Fair</option>
    <option value="Used">Used</option>
</select>

<select name="listing_type" required>
    <option value="">-- Select Type --</option>
    <option value="sale">Sell</option>
    <option value="rent">Rent</option>
    <option value="both">Sell & rent</option>
</select>
```

**Fixes:**
- Added `required` attribute to condition select (browser validation)
- Added `required` attribute to listing_type select (browser validation)
- Added default placeholder option with empty value to both selects
- Added explicit `value` attributes to all condition options
- HTML5 form validation now prevents submission without selection
- Server-side validation catches any empty values

---

## File 3: app/templates/products/edit.html

### BEFORE ❌
```html
<select name="condition">
    {% for condition in ['New', 'Like New', 'Good', 'Fair', 'Used'] %}
        <option {% if product.condition == condition %}selected{% endif %}>{{ condition }}</option>
    {% endfor %}
</select>
```

**Problems:**
- Same as form.html: no `required`, no value attribute, no default option
- Options rendered without explicit value attributes

### AFTER ✅
```html
<select name="condition" required>
    <option value="">-- Select Condition --</option>
    {% for condition in ['New', 'Like New', 'Good', 'Fair', 'Used'] %}
        <option value="{{ condition }}" {% if product.condition == condition %}selected{% endif %}>{{ condition }}</option>
    {% endfor %}
</select>
```

**Fixes:**
- Added `required` attribute
- Added default empty option
- Added explicit `value="{{ condition }}"` to each option
- Same browser validation as form.html

---

## Summary of Changes

| File | Change | Impact |
|------|--------|--------|
| app/products/routes.py | Added validation & type conversion in create() | Prevents invalid data from reaching database |
| app/products/routes.py | Added validation & type conversion in edit() | Prevents invalid data from reaching database |
| app/templates/products/form.html | Added required attributes & default options | Client-side validation + server receives correct values |
| app/templates/products/edit.html | Added required attributes & default options | Client-side validation + server receives correct values |

**Total Lines Changed:** ~120 lines of validation code
**Files Modified:** 2 files
**Forms Fixed:** 2 forms (add & edit)
**Error Type Fixed:** HTTP 400 Bad Request on form submission
