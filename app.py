import io
import re
import pandas as pd
import phonenumbers
import streamlit as st

# Preferred business/reputable domains given higher priority during email deduplication
PREFERRED_DOMAINS = [
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "protonmail.com",
    "zoho.com",
]

# Common variations of column names in raw recruitment/lead exports
COLUMN_ALIASES = {
    "first_name": ["first name", "firstname", "first", "fname", "given name"],
    "last_name": ["last name", "lastname", "last", "lname", "surname", "family name"],
    "full_name": ["full name", "fullname", "name", "contact name", "candidate name", "person name"],
    "email": ["email", "e-mail", "email address", "mail", "contact email", "primary email"],
    "phone": ["phone", "phone number", "mobile", "mobile number", "cell", "contact number", "telephone"],
    "location": ["location", "city", "address", "state", "candidate location", "current location", "metro"],
    "current_company": ["current company", "company", "organization", "employer", "current employer", "firm"],
}

PREFIXES = {"mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "dr", "dr.", "prof", "prof."}


def split_full_name(name_str) -> tuple[str | None, str | None]:
    """
    Splits a full name string into First Name and Last Name.
    Strips common honorifics and handles single-name or multi-part formats.
    """
    if pd.isna(name_str):
        return None, None

    cleaned = str(name_str).strip()
    if not cleaned or cleaned.lower() in ["nan", "none"]:
        return None, None

    # Handle 'Last, First' comma-separated format
    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",", 1) if p.strip()]
        if len(parts) == 2:
            last_name, first_name = parts[0], parts[1]
            return first_name.title(), last_name.title()

    tokens = cleaned.split()

    # Drop leading prefixes like Dr., Mr., etc.
    if tokens and tokens[0].lower() in PREFIXES:
        tokens = tokens[1:]

    if not tokens:
        return None, None

    if len(tokens) == 1:
        return tokens[0].title(), None

    # First token becomes first name, remaining tokens form the last name
    first_name = tokens[0].title()
    last_name = " ".join(tokens[1:]).title()

    return first_name, last_name


def map_columns(df: pd.DataFrame) -> dict:
    """Finds best matching column names in the uploaded DataFrame."""
    normalized_cols = {col: re.sub(r"[_\s\W]+", " ", str(col)).strip().lower() for col in df.columns}
    mapping = {}

    for target_col, aliases in COLUMN_ALIASES.items():
        found = None
        for orig_col, norm_col in normalized_cols.items():
            if norm_col in aliases:
                found = orig_col
                break
        mapping[target_col] = found

    return mapping


def extract_best_email(val) -> str | None:
    """Extracts valid emails and prioritizes established providers if multiple exist."""
    if pd.isna(val):
        return None
    val_str = str(val).lower()
    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", val_str)
    if not emails:
        return None

    # Check for preferred domain first
    for email in emails:
        domain = email.split("@")[-1]
        if domain in PREFERRED_DOMAINS:
            return email
    return emails[0]


def format_phone_number(val, default_region="US") -> str | None:
    """Extracts and standardizes the first usable phone number to E.164 format."""
    if pd.isna(val):
        return None
    val_str = str(val).strip()

    # Split common multi-phone separators
    candidates = re.split(r"[,;/|\n]", val_str)

    for item in candidates:
        cleaned = re.sub(r"[^\d+]", "", item)
        if len(cleaned) < 7:
            continue
        try:
            parsed = phonenumbers.parse(item, default_region)
            if phonenumbers.is_possible_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            continue

    # Fallback clean for unformatted domestic strings
    digits = re.sub(r"\D", "", val_str)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) >= 10:
        return f"+{digits}"

    return None


def clean_dataframe(df_raw: pd.DataFrame, region: str) -> tuple[pd.DataFrame, dict]:
    """Extracts target fields, splits names, drops empties, and dedupes."""
    mapping = map_columns(df_raw)
    cleaned = pd.DataFrame()

    # Pull mapped data or initialize None
    for target in ["first_name", "last_name", "full_name", "email", "phone", "location", "current_company"]:
        src_col = mapping.get(target)
        if src_col and src_col in df_raw.columns:
            cleaned[target] = df_raw[src_col]
        else:
            cleaned[target] = None

    initial_count = len(cleaned)

    # Name Resolution: Use split logic when individual name fields are missing
    has_first = cleaned["first_name"].notna() & (cleaned["first_name"].astype(str).str.strip() != "")
    has_last = cleaned["last_name"].notna() & (cleaned["last_name"].astype(str).str.strip() != "")
    needs_name_split = ~(has_first & has_last) & cleaned["full_name"].notna()

    if needs_name_split.any():
        split_results = cleaned.loc[needs_name_split, "full_name"].apply(split_full_name)
        
        # Fill missing first names
        cleaned.loc[needs_name_split & ~has_first, "first_name"] = [
            res[0] for res in split_results[~has_first[needs_name_split]]
        ]
        # Fill missing last names
        cleaned.loc[needs_name_split & ~has_last, "last_name"] = [
            res[1] for res in split_results[~has_last[needs_name_split]]
        ]

    # Clean text columns
    for text_col in ["first_name", "last_name", "location", "current_company"]:
        cleaned[text_col] = cleaned[text_col].astype(str).str.strip()
        cleaned[text_col] = cleaned[text_col].replace({"nan": None, "None": None, "": None})

    # Normalize email & phone
    cleaned["email"] = cleaned["email"].apply(extract_best_email)
    cleaned["phone"] = cleaned["phone"].apply(lambda p: format_phone_number(p, default_region=region))

    # Drop records missing either email OR phone
    cleaned = cleaned.dropna(subset=["email", "phone"])
    valid_contacts_count = len(cleaned)

    # Deduplicate: unique email, then unique phone
    cleaned = cleaned.drop_duplicates(subset=["email"], keep="first")
    cleaned = cleaned.drop_duplicates(subset=["phone"], keep="first")
    final_count = len(cleaned)

    # Retain strictly the required 6 columns
    output_cols = ["first_name", "last_name", "email", "phone", "location", "current_company"]
    cleaned = cleaned[output_cols]

    stats = {
        "initial": initial_count,
        "dropped_missing_contact": initial_count - valid_contacts_count,
        "dropped_duplicates": valid_contacts_count - final_count,
        "final": final_count,
    }

    # Rename to clean presentation headers
    cleaned.columns = ["First Name", "Last Name", "Email", "Phone", "Location", "Current Company"]
    return cleaned, stats


# --- STREAMLIT UI ---
st.set_page_config(page_title="Contact Data Scrubber", page_icon="⚡", layout="wide")

st.title("Contact Data Cleaner & Deduplicator")
st.caption("Upload raw candidate/lead CSVs. Automatically parses names, standardizes phone/email, drops incomplete entries, and removes duplicates.")

with st.sidebar:
    st.header("Settings")
    selected_region = st.selectbox(
        "Default Phone Region Code",
        options=["US", "IN", "GB", "CA", "AU"],
        index=0,
        help="Used to format local numbers lacking an international country code.",
    )
    st.markdown("---")
    st.markdown("**Field Mapping Capabilities:**")
    st.markdown("- **Names**: Auto-detects separate First/Last columns OR splits a single Full Name column")
    st.markdown("- **Email**: Extracts primary address, prioritizing standard domains")
    st.markdown("- **Phone**: Normalizes to E.164 standard")
    st.markdown("- **Output**: First Name, Last Name, Email, Phone, Location, Current Company")

uploaded_files = st.file_uploader(
    "Choose CSV files",
    type=["csv"],
    accept_multiple_files=True,
    help="Upload one or multiple raw CSV files.",
)

if uploaded_files:
    dfs = []
    for f in uploaded_files:
        try:
            temp_df = pd.read_csv(f, low_memory=False, encoding_errors="replace")
            temp_df["__source_file"] = f.name
            dfs.append(temp_df)
        except Exception as e:
            st.error(f"Error reading {f.name}: {e}")

    if dfs:
        combined_raw = pd.concat(dfs, ignore_index=True)
        st.info(f"Loaded **{len(uploaded_files)}** file(s) totaling **{len(combined_raw):,}** raw records.")

        with st.spinner("Standardizing names, validating contacts, and deduplicating..."):
            cleaned_data, summary = clean_dataframe(combined_raw, region=selected_region)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Raw Rows", f"{summary['initial']:,}")
        col2.metric("Dropped (Missing Email/Phone)", f"-{summary['dropped_missing_contact']:,}")
        col3.metric("Duplicates Removed", f"-{summary['dropped_duplicates']:,}")
        col4.metric("Final Records", f"{summary['final']:,}")

        st.subheader("Cleaned Dataset Preview")
        st.dataframe(cleaned_data.head(50), use_container_width=True)

        st.subheader("Export Cleaned Data")
        exp_col1, exp_col2 = st.columns(2)

        # CSV Download
        csv_buffer = cleaned_data.to_csv(index=False).encode("utf-8")
        exp_col1.download_button(
            label="Download as CSV",
            data=csv_buffer,
            file_name="cleaned_contacts.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # Excel Download
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            cleaned_data.to_excel(writer, index=False, sheet_name="CleanedContacts")
        exp_col2.download_button(
            label="Download as Excel (.xlsx)",
            data=excel_buffer.getvalue(),
            file_name="cleaned_contacts.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
