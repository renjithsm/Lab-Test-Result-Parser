from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
import pytesseract
import io
import re

app = FastAPI()

def is_header(line):
    headers = ["DIFFERENTIAL COUNT", "ABSOLUTE COUNTS", "PLATELETS", "EQUIPMENT", "METHOD", "SPECIMEN", "END OF REPORT"]
    return any(h in line.upper() for h in headers)

def is_noise(line):
    noise_keywords = ["Dr.", "Hospital", "Time", "Sample", "Date", "MD", "B.Sc", "Pathology", "Report", "Release"]
    return any(n in line for n in noise_keywords) or len(line.strip()) < 3

def clean_unit(unit):
    if unit:
        return unit.replace("/cumm", "/uL").replace("gm/dl", "g/dL").replace("Pg", "pg").strip()
    return "Not Specified"

def parse_lab_tests(text):
    lines = text.split("\n")
    results = []
    seen_tests = set()

    # Combine adjacent lines if needed
    combined_lines = []
    buffer = ""
    for line in lines:
        line = line.strip()
        if is_noise(line) or is_header(line):
            continue
        if re.search(r"[\d.]+\s*[-–]\s*[\d.]+", line):  # likely a reference range
            buffer += " " + line
            combined_lines.append(buffer.strip())
            buffer = ""
        elif re.search(r"[A-Za-z].*[\d.]+", line):  # looks like a test + value
            if buffer:
                combined_lines.append(buffer.strip())
            buffer = line
        else:
            buffer += " " + line
    if buffer:
        combined_lines.append(buffer.strip())

    # Regex to match cleaned lines
    pattern = r"(?P<test_name>[A-Za-z \(\)\-\/\.]+?)[:\s]+(?P<value>[\d.]+)\s*(?P<unit>g/dL|gm/dl|%|fl|pg|cells/cumm|mill/cmm|/uL|/cumm)?(?:\s*\(?\s*(?P<ref_range>[\d.]+\s*-\s*[\d.]+)\s*\)?)?"

    for line in combined_lines:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            test_name = match.group("test_name").strip()
            if test_name.lower() in seen_tests:
                continue
            seen_tests.add(test_name.lower())

            value = match.group("value").strip()
            unit = clean_unit(match.group("unit"))
            ref_range = match.group("ref_range") if match.group("ref_range") else "Not Specified"

            # Range check
            out_of_range = False
            try:
                if ref_range != "Not Specified":
                    low, high = map(float, re.findall(r"[\d.]+", ref_range))
                    val = float(value)
                    if val < low or val > high:
                        out_of_range = True
            except:
                pass

            results.append({
                "test_name": test_name,
                "test_value": value,
                "bio_reference_range": ref_range,
                "test_unit": unit,
                "lab_test_out_of_range": out_of_range
            })

    return {
        "is_success": True,
        "data": results
    }

@app.post("/get-lab-tests")
async def get_lab_tests(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        text = pytesseract.image_to_string(image)
        extracted = parse_lab_tests(text)
        return JSONResponse(content=extracted)
    except Exception as e:
        return JSONResponse(content={"is_success": False, "error": str(e)}, status_code=500)
