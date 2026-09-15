"""
Tests for restocking API endpoints.
"""
import pytest


class TestRestockingRecommendations:
    """Test suite for restocking recommendation endpoints."""

    def test_get_recommendations_returns_list(self, client):
        """Test getting recommendations for a budget."""
        response = client.get("/api/restocking/recommendations?budget=1000")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

    def test_recommendations_respect_budget(self, client):
        """Test that recommended line totals never exceed the requested budget."""
        budget = 2000
        response = client.get(f"/api/restocking/recommendations?budget={budget}")
        data = response.json()

        total = sum(item["line_total"] for item in data)
        assert total <= budget

    def test_recommendations_zero_budget(self, client):
        """Test that a zero budget yields no recommendations."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200
        assert response.json() == []

    def test_recommendations_negative_budget_rejected(self, client):
        """Test that a negative budget is rejected."""
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 400

    def test_recommendations_prioritize_increasing_trend(self, client):
        """Test that increasing-trend items with a shortfall are recommended and
        items with no shortfall (e.g. decreasing trend, adequately stocked) are not."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        skus = [item["sku"] for item in data]
        assert "WDG-001" in skus  # increasing trend, understocked
        assert "MTR-304" not in skus  # decreasing trend, adequately stocked

    def test_recommendations_sorted_by_urgency(self, client):
        """Test that recommendations are ordered by descending urgency score."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        scores = [item["urgency_score"] for item in data]
        assert scores == sorted(scores, reverse=True)


class TestRestockingOrders:
    """Test suite for restocking order submission endpoints."""

    def test_get_restocking_orders_returns_list(self, client):
        """Test getting all submitted restocking orders."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order."""
        payload = {
            "budget": 1000,
            "items": [
                {
                    "sku": "WDG-001",
                    "item_name": "Industrial Widget Type A",
                    "quantity": 10,
                    "unit_cost": 15.50,
                    "line_total": 155.00,
                    "lead_time_days": 18
                },
                {
                    "sku": "PSU-501",
                    "item_name": "5V 10A Switching Power Supply",
                    "quantity": 5,
                    "unit_cost": 18.99,
                    "line_total": 94.95,
                    "lead_time_days": 6
                }
            ]
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["order_number"].startswith("RSO-")
        assert data["total_cost"] == pytest.approx(155.00 + 94.95)
        assert data["max_lead_time_days"] == 18
        assert data["expected_delivery_date"] > data["submitted_date"]

    def test_create_restocking_order_requires_items(self, client):
        """Test that submitting an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 500, "items": []})
        assert response.status_code == 400

    def test_created_order_appears_in_list(self, client):
        """Test that a newly submitted order shows up in the orders list."""
        payload = {
            "budget": 200,
            "items": [
                {
                    "sku": "GSK-203",
                    "item_name": "High-Temperature Gasket",
                    "quantity": 20,
                    "unit_cost": 4.25,
                    "line_total": 85.00,
                    "lead_time_days": 18
                }
            ]
        }
        create_response = client.post("/api/restocking/orders", json=payload)
        order_number = create_response.json()["order_number"]

        list_response = client.get("/api/restocking/orders")
        order_numbers = [order["order_number"] for order in list_response.json()]
        assert order_number in order_numbers
