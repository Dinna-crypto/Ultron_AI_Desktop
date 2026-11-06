"""
buggy_test.py
A deliberately broken script for testing Ultron's code_analyzer.py.
Contains ONE bug: `price` is referenced before it's ever defined.
"""

def calculate_total(quantity):
    tax_rate = 0.08
    subtotal = quantity * price  # <-- bug: 'price' was never defined
    total = subtotal * (1 + tax_rate)
    return total


if __name__ == "__main__":
    result = calculate_total(5)
    print(f"Total: {result}")