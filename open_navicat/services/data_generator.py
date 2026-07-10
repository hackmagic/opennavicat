"""Pattern-based test data generator — no AI required."""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta

from open_navicat.models.table_schema import TableInfo

# ponytail: pattern registry — extend by adding (column_pattern, generator_fn) tuples

_NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Hank",
    "Iris", "Jack", "Kate", "Leo", "Mia", "Noah", "Olivia", "Paul",
    "Quinn", "Rose", "Sam", "Tina", "Uma", "Vic", "Wendy", "Xander",
    "Yara", "Zane", "张三", "李四", "王五", "赵六", "钱七", "孙八",
]

_SURNAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas",
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵",
]

_DOMAINS = ["example.com", "test.org", "demo.net", "sample.io", "mail.com"]

_STREETS = [
    "Main St", "Oak Ave", "Pine Rd", "Elm Blvd", "Cedar Ln",
    "Maple Dr", "1st Ave", "2nd St", "3rd Blvd", "Park Rd",
    "中山路", "解放路", "人民路", "建设路", "文化路",
]

_CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Hangzhou",
]

_COUNTRIES = ["US", "CN", "JP", "UK", "DE", "FR", "KR", "CA", "AU", "BR"]


class DataGeneratorService:
    """Generate test data based on column name and type patterns."""

    _instance = None

    def __new__(cls) -> DataGeneratorService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def generate(self, table_info: TableInfo, count: int) -> list[dict]:
        """Generate count rows of test data based on table schema."""
        rows = []
        for _ in range(count):
            row = {}
            for col in table_info.columns:
                if col.is_auto_increment:
                    continue  # skip auto-increment columns
                row[col.name] = self._generate_value(col.name, col.data_type, col.nullable)
            rows.append(row)
        return rows

    def _generate_value(self, col_name: str, data_type: str, nullable: bool) -> object:
        """Generate a single value based on column name and type."""
        # 10% chance of NULL for nullable columns
        if nullable and random.random() < 0.1:
            return None

        col_lower = col_name.lower()
        dtype = (data_type or "").lower()

        # Pattern matching by column name (highest priority)
        gen = self._match_name_pattern(col_lower)
        if gen is not None:
            return gen

        # Fallback to type-based generation
        return self._match_type_pattern(dtype)

    def _match_name_pattern(self, col_name: str) -> object | None:
        """Match column name against known patterns."""
        # Email
        if any(k in col_name for k in ("email", "mail", "e_mail")):
            return self._gen_email()

        # Phone
        if any(k in col_name for k in ("phone", "tel", "mobile", "cell")):
            return self._gen_phone()

        # Name (first/last/full)
        if col_name in ("name", "username", "user_name", "fullname", "full_name"):
            return f"{random.choice(_SURNAMES)}{random.choice(_NAMES)}"
        if any(k in col_name for k in ("first_name", "firstname", "given_name")):
            return random.choice(_NAMES)
        if any(k in col_name for k in ("last_name", "lastname", "surname", "family_name")):
            return random.choice(_SURNAMES)

        # Address
        if any(k in col_name for k in ("address", "addr", "street")):
            return self._gen_address()

        # City
        if "city" in col_name:
            return random.choice(_CITIES)

        # Country
        if "country" in col_name:
            return random.choice(_COUNTRIES)

        # Zip/Postal code
        if any(k in col_name for k in ("zip", "postal", "postcode")):
            return f"{random.randint(10000, 99999)}"

        # URL
        if any(k in col_name for k in ("url", "website", "link", "homepage")):
            return self._gen_url()

        # UUID
        if any(k in col_name for k in ("uuid", "guid")):
            return str(uuid.uuid4())

        # Password/Hash
        if any(k in col_name for k in ("password", "passwd", "hash", "secret")):
            return self._gen_password()

        # IP address
        if any(k in col_name for k in ("ip", "ip_address", "ipaddr")):
            return f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

        # Title/Subject
        if any(k in col_name for k in ("title", "subject")):
            return self._gen_title()

        # Description/Content/Body/Text/Remark/Note/Comment
        if any(k in col_name for k in ("description", "content", "body", "text", "remark", "note", "comment", "summary")):
            return self._gen_text()

        # Status
        if "status" in col_name:
            return random.choice(["active", "inactive", "pending", "archived"])

        # Type/Category
        if any(k in col_name for k in ("type", "category", "kind")):
            return random.choice(["type_a", "type_b", "type_c", "default"])

        # Price/Cost/Amount/Balance
        if any(k in col_name for k in ("price", "cost", "amount", "balance", "total", "sum")):
            return round(random.uniform(1.0, 9999.99), 2)

        # Quantity/Count/Num
        if any(k in col_name for k in ("quantity", "count", "num", "amount")):
            return random.randint(1, 100)

        # Score/Rating
        if any(k in col_name for k in ("score", "rating", "rank")):
            return round(random.uniform(1.0, 10.0), 1)

        # Lat/Latitude
        if any(k in col_name for k in ("lat", "latitude")):
            return round(random.uniform(-90.0, 90.0), 6)

        # Lng/Lon/Longitude
        if any(k in col_name for k in ("lng", "lon", "longitude")):
            return round(random.uniform(-180.0, 180.0), 6)

        # Created/Updated timestamps
        if any(k in col_name for k in ("created_at", "create_time", "created", "create_date")):
            return self._gen_past_datetime()
        if any(k in col_name for k in ("updated_at", "update_time", "modified", "modify_time")):
            return self._gen_past_datetime()

        # Deleted/Is deleted flags
        if any(k in col_name for k in ("deleted", "is_deleted", "isdelete")):
            return 0

        # Enabled/Active/Is active flags
        if any(k in col_name for k in ("enabled", "is_active", "active")):
            return random.choice([0, 1])

        return None  # no pattern match — let type fallback handle it

    def _match_type_pattern(self, dtype: str) -> object:
        """Generate value based on SQL data type."""
        if not dtype:
            return "test_value"

        # Integer types
        if any(t in dtype for t in ("int", "serial")):
            return random.randint(1, 10000)

        # Float/Decimal
        if any(t in dtype for t in ("float", "double", "decimal", "numeric", "real")):
            return round(random.uniform(0.01, 9999.99), 2)

        # Boolean
        if "bool" in dtype:
            return random.choice([0, 1])

        # Date
        if dtype == "date":
            d = datetime.now() - timedelta(days=random.randint(0, 365))
            return d.strftime("%Y-%m-%d")

        # Time
        if dtype == "time":
            return f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"

        # Datetime/Timestamp
        if any(t in dtype for t in ("datetime", "timestamp")):
            return self._gen_past_datetime()

        # JSON
        if "json" in dtype:
            return '{"key": "value"}'

        # Text/VARCHAR/CHAR — generic string
        if any(t in dtype for t in ("char", "text", "enum", "set", "varchar")):
            return self._gen_text(short=True)

        # Blob/Binary
        if any(t in dtype for t in ("blob", "binary", "varbinary")):
            return None

        return "test_value"

    # ---- generators ----

    def _gen_email(self) -> str:
        name = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(5, 12)))
        return f"{name}@{random.choice(_DOMAINS)}"

    def _gen_phone(self) -> str:
        return f"+{random.randint(1, 86)}{random.randint(1000000000, 9999999999)}"

    def _gen_address(self) -> str:
        return f"{random.randint(1, 999)} {random.choice(_STREETS)}, {random.choice(_CITIES)}"

    def _gen_url(self) -> str:
        paths = ["about", "contact", "help", "blog", "products", "services"]
        return f"https://www.{random.choice(_DOMAINS)}/{random.choice(paths)}"

    def _gen_password(self) -> str:
        chars = string.ascii_letters + string.digits + "!@#$%"
        return "".join(random.choices(chars, k=16))

    def _gen_title(self) -> str:
        adjectives = ["New", "Best", "Top", "Essential", "Advanced", "Quick", "Simple", "Modern"]
        nouns = ["Guide", "Tutorial", "Review", "Introduction", "Overview", "Summary", "Analysis", "Report"]
        return f"{random.choice(adjectives)} {random.choice(nouns)}"

    def _gen_text(self, short: bool = False) -> str:
        if short:
            words = ["lorem", "ipsum", "dolor", "sit", "amet", "data", "test", "sample", "example", "demo"]
            n = random.randint(3, 8)
            return " ".join(random.choices(words, k=n))
        paragraphs = [
            "This is sample data generated for testing purposes. It represents realistic content that might appear in a production database.",
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            "The quick brown fox jumps over the lazy dog. This pangram contains every letter of the English alphabet at least once.",
            "测试数据用于验证系统功能。这是一段中文示例文本，模拟真实数据库中可能出现的内容。",
        ]
        return random.choice(paragraphs)

    def _gen_past_datetime(self) -> str:
        dt = datetime.now() - timedelta(days=random.randint(0, 365), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        return dt.strftime("%Y-%m-%d %H:%M:%S")


# Singleton
data_generator = DataGeneratorService()
