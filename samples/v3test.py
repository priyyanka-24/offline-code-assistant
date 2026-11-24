

import datetime
import json

# Class to represent a book
class Book:
    def __init__(self, title, author, year):
        self.title = title
        self.author = author
        self.year = year
        self.is_borrowed = False

    def borrow(self):
        if self.is_borrowed == True:
            print("Book already borrowed")
        else:
            self.is_borrowed = True
            print("Book borrowed successfully")

    def return_book(self):
        if self.is_borrowed == False:
            print("Book was never borrowed")
        else:
            self.is_borrowed = False
            print("Book returned successfully")

# Class to represent the library
class Library:
    def __init__(self):
        self.books = []

    def add_book(self, book):
        # Logical error: appending wrong variable
        self.books.append("book")  # Should append book object

    def list_books(self):
        for b in self.books:
            # Runtime error: treating string as object
            print(f"{b.title} by {b.author} ({b.year})")

    def borrow_book(self, title):
        for b in self.books:
            if b.title == title:
                b.borrow()
                return
        print("Book not found")

    def save_to_file(self, filename):
        # Syntax error: missing closing parenthesis
        with open(filename, "w") as f:
            json.dump([vars(b) for b in self.books], f

    def load_from_file(self, filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                for item in data:
                    # NameError: Book not imported properly
                    new_book = Book(item["title"], item["author"], item["year"])
                    self.books.append(new_book)
        except FileNotFoundError:
            print("File not found")

# Function to simulate user interaction
def run_library():
    lib = Library()

    # Typo: 'bok' instead of 'book'
    bok1 = Book("1984", "George Orwell", 1949)
    bok2 = Book("To Kill a Mockingbird", "Harper Lee", 1960)

    # Logical error: adding wrong variable
    lib.add_book(bok1)
    lib.add_book(bok2)

    # Runtime error: borrowing book not in list
    lib.borrow_book("The Great Gatsby")

    # Type error: passing int instead of string
    lib.borrow_book(123)

    # Syntax error: missing colon
    if True
        lib.list_books()

    # Undefined variable error
    print(total_books)

    # Wrong method call: missing parentheses
    lib.save_to_file("library.json")

if __name__ == "__main__":
    run_library
