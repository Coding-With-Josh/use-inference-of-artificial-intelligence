import csv
from io import StringIO


def parse_csv(text):
    result = []
    try:
        f = StringIO(text)
        reader = csv.DictReader(f)
        for row in reader:
            result.append(dict(row))
    except Exception as e:
        result.append({"error": str(e)})
    return result
