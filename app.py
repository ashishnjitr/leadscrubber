import io
import re
import pandas as pd
import phonenumbers
import streamlit as st

# Preferred reputable domains given priority during email deduplication
# Comprehensive list of reputable consumer, business, enterprise, and regional domains
PREFERRED_DOMAINS = [
    # Top Consumer & Enterprise Workspace Giants
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "ymail.com",
    "rocketmail.com",
    "icloud.com",
    "me.com",
    "mac.com",
    
    # Privacy & Secure Webmail
    "protonmail.com",
    "proton.me",
    "tutanota.com",
    "tutamail.com",
    "zoho.com",
    "zohomail.com",
    "fastmail.com",
    "hey.com",
    
    # Major US Telecom & ISP Providers
    "aol.com",
    "aim.com",
    "comcast.net",
    "verizon.net",
    "att.net",
    "sbcglobal.net",
    "bellsouth.net",
    "cox.net",
    "charter.net",
    "spectrum.net",
    "earthlink.net",
    
    # Regional & International Webmail (UK, Europe, APAC, India)
    "yahoo.co.uk",
    "yahoo.co.in",
    "yahoo.ca",
    "yahoo.com.au",
    "hotmail.co.uk",
    "rediffmail.com",
    "gmx.com",
    "gmx.net",
    "web.de",
    "mail.com",
    "yandex.com",
    "yandex.ru",
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
    "linkedin_url": [
        "linkedin",
        "linkedin url",
        "linkedin profile",
        "linkedin link",
        "profile link",
        "social url",
        "linkedin_url",
    ],
}

PREFIXES = {"mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "dr", "dr.", "prof", "prof."}


def split_full_name(name_str) -> tuple[str | None, str | None]:
    """Splits a full name string into First Name and Last Name."""
    if pd.isna(name_str):
        return None, None

    cleaned = str(name_str).strip()
    if not cleaned or cleaned.lower() in ["nan", "none"]:
        return None, None

    # Handle 'Last, First' format
    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",", 1) if p.strip()]
        if len(parts) == 2:
            return parts[1].title(), parts[0].title()

    tokens = cleaned.split()
    if tokens and tokens[0].lower() in PREFIXES:
        tokens = tokens[1:]

    if not tokens:
        return None, None
    if len(tokens) == 1:
        return tokens[0].title(), None

    return tokens[0].title(), " ".join(tokens[1:]).title()


def map_columns(df: pd.DataFrame) -> dict:
    """Finds matching column names in the uploaded DataFrame."""
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

    for email in emails:
        domain = email.split("@")[-1]
        if domain in PREFERRED_DOMAINS:
            return email
    return emails[0]


def format_phone_number(val, default_region="US") -> str | None:
    """Standardizes phone numbers to E.164 format."""
    if pd.isna(val):
        return None
    val_str = str(val).strip()

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

    digits = re.sub(r"\D", "", val_str)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) >= 10:
        return f"+{digits}"

    return None


def clean_linkedin_url(val) -> str | None:
    """Detects, normalizes, and extracts clean LinkedIn profile links."""
    if pd.isna(val):
        return None
    val_str = str(val).strip()

    match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_\-%]+)", val_str, re.IGNORECASE)
    if match:
        profile_slug = match.group(1).rstrip("/")
        return f"https://www.linkedin.com/in/{profile_slug}"

    # Also catch handles or raw company/in links
    if "linkedin.com" in val_str.lower():
        cleaned_link = re.sub(r"\?.*$", "", val_str)  # Remove tracking parameters
        if not cleaned_link.startswith("http"):
            cleaned_link = f"https://{cleaned_link}"
        return cleaned_link

    return None
# Convert to a set for O(1) instantaneous lookup
PREFERRED_DOMAINS_SET = set(PREFERRED_DOMAINS)

# Common throwaway/temporary email providers to deprioritize or filter out
DISPOSABLE_DOMAINS = {
    "tempmail.com", "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "throwawaymail.com", "trashmail.com", "yopmail.com"
}

def extract_best_email(val) -> str | None:
    """
    Extracts valid emails and prioritizes established providers and clean business domains
    over generic or disposable addresses.
    """
    if pd.isna(val):
        return None
    val_str = str(val).lower()
    
    # Strict regex matching valid email patterns
    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", val_str)
    if not emails:
        return None

    # Filter out disposable/trash domains if possible
    clean_emails = [e for e in emails if e.split("@")[-1] not in DISPOSABLE_DOMAINS]
    pool = clean_emails if clean_emails else emails

    # 1. First priority: Established preferred webmail/workspace provider
    for email in pool:
        domain = email.split("@")[-1]
        if domain in PREFERRED_DOMAINS_SET:
            return email

    # 2. Second priority: Likely corporate domain (contains standard .com, .io, .org, etc., but not disposable)
    for email in pool:
        domain = email.split("@")[-1]
        if domain not in DISPOSABLE_DOMAINS:
            return email

    # 3. Fallback
    return pool[0]

def process_datasets(df_raw: pd.DataFrame, region: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Generates Dataset 1 (Direct Contacts) and Dataset 2 (LinkedIn Leads)."""
    mapping = map_columns(df_raw)
    base_df = pd.DataFrame()

    target_keys = ["first_name", "last_name", "full_name", "email", "phone", "location", "current_company", "linkedin_url"]
    for target in target_keys:
        src_col = mapping.get(target)
        if src_col and src_col in df_raw.columns:
            base_df[target] = df_raw[src_col]
        else:
            base_df[target] = None

    # Resolve names
    has_first = base_df["first_name"].notna() & (base_df["first_name"].astype(str).str.strip() != "")
    has_last = base_df["last_name"].notna() & (base_df["last_name"].astype(str).str.strip() != "")
    needs_name_split = ~(has_first & has_last) & base_df["full_name"].notna()

    if needs_name_split.any():
        split_results = base_df.loc[needs_name_split, "full_name"].apply(split_full_name)
        base_df.loc[needs_name_split & ~has_first, "first_name"] = [
            res[0] for res in split_results[~has_first[needs_name_split]]
        ]
        base_df.loc[needs_name_split & ~has_last, "last_name"] = [
            res[1] for res in split_results[~has_last[needs_name_split]]
        ]

    # Clean shared string columns
    for col in ["first_name", "last_name", "location", "current_company"]:
        base_df[col] = base_df[col].astype(str).str.strip()
        base_df[col] = base_df[col].replace({"nan": None, "None": None, "": None})

    # Standardize contact and profile points
    base_df["email"] = base_df["email"].apply(extract_best_email)
    base_df["phone"] = base_df["phone"].apply(lambda p: format_phone_number(p, default_region=region))
    base_df["linkedin_url"] = base_df["linkedin_url"].apply(clean_linkedin_url)

    # --- DATASET 1: Verified Direct Contacts (Requires Email AND Phone) ---
    df1 = base_df.dropna(subset=["email", "phone"]).copy()
    initial_d1_count = len(df1)
    df1 = df1.drop_duplicates(subset=["email"], keep="first")
    df1 = df1.drop_duplicates(subset=["phone"], keep="first")
    df1_cols = ["first_name", "last_name", "email", "phone", "location", "current_company"]
    df1 = df1[df1_cols]
    df1.columns = ["First Name", "Last Name", "Email", "Phone", "Location", "Current Company"]

    # --- DATASET 2: LinkedIn & Sourcing Leads (Requires LinkedIn URL) ---
    df2 = base_df.dropna(subset=["linkedin_url"]).copy()
    initial_d2_count = len(df2)
    # Deduplicate strictly on unique normalized LinkedIn profile link
    df2 = df2.drop_duplicates(subset=["linkedin_url"], keep="first")
    df2_cols = ["first_name", "last_name", "location", "current_company", "linkedin_url"]
    df2 = df2[df2_cols]
    df2.columns = ["First Name", "Last Name", "Location", "Current Company", "LinkedIn URL"]

    metrics = {
        "raw_total": len(df_raw),
        "d1_initial": initial_d1_count,
        "d1_final": len(df1),
        "d2_initial": initial_d2_count,
        "d2_final": len(df2),
    }

    return df1, df2, metrics


# --- STREAMLIT UI ---
st.set_page_config(page_title="Candidate & Lead Data Scrubber", page_icon="⚡", layout="wide")

st.title("Candidate & Lead Data Scrubber")
st.caption("Batch process raw CSVs into two targeted datasets: verified direct contacts and LinkedIn sourcing profiles.")

with st.sidebar:
    st.header("Settings")
    selected_region = st.selectbox(
        "Default Phone Region Code",
        options=["US", "IN", "GB", "CA", "AU"],
        index=0,
        help="Used to format numbers lacking a country code.",
    )
    st.markdown("---")
    st.markdown("### Output Specifications")
    st.markdown("**Dataset 1 (Direct Contacts):**\n- Requires **both** Email and Phone\n- Formatted E.164 & deduplicated\n- Columns: First, Last, Email, Phone, Location, Company")
    st.markdown("**Dataset 2 (LinkedIn Profiles):**\n- Requires **LinkedIn URL**\n- Deduplicated by unique profile link\n- Columns: First, Last, Location, Company, LinkedIn URL")

uploaded_files = st.file_uploader(
    "Choose CSV files",
    type=["csv"],
    accept_multiple_files=True,
    help="Upload your raw CSV exports.",
)

if uploaded_files:
    dfs = []
    for f in uploaded_files:
        try:
            temp_df = pd.read_csv(f, low_memory=False, encoding_errors="replace")
            dfs.append(temp_df)
        except Exception as e:
            st.error(f"Error reading {f.name}: {e}")

    if dfs:
        combined_raw = pd.concat(dfs, ignore_index=True)

        with st.spinner("Processing names, validating emails/phones, and extracting LinkedIn profiles..."):
            dataset_contacts, dataset_linkedin, stats = process_datasets(combined_raw, region=selected_region)

        col1, col2, col3 = st.columns(3)
        col1.metric("Raw Rows Uploaded", f"{stats['raw_total']:,}")
        col2.metric("Dataset 1 (Email + Phone)", f"{stats['d1_final']:,}")
        col3.metric("Dataset 2 (LinkedIn Profiles)", f"{stats['d2_final']:,}")

        # Combined Full Excel Workbook
        master_excel_buffer = io.BytesIO()
        with pd.ExcelWriter(master_excel_buffer, engine="openpyxl") as writer:
            dataset_contacts.to_excel(writer, index=False, sheet_name="Email_Phone_Contacts")
            dataset_linkedin.to_excel(writer, index=False, sheet_name="LinkedIn_Profiles")

        st.download_button(
            label="Download Complete Excel Package (Both Datasets in Separate Tabs)",
            data=master_excel_buffer.getvalue(),
            file_name="cleaned_candidates_complete.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        tab1, tab2 = st.tabs(["Dataset 1: Phone & Email Contacts", "Dataset 2: LinkedIn Profiles"])

        with tab1:
            st.subheader("Verified Direct Contacts")
            st.caption("Only rows with both a valid Phone Number and Email address. Single contact point kept per person.")
            st.dataframe(dataset_contacts.head(50), use_container_width=True)

            c1, c2 = st.columns(2)
            c1.download_button(
                label="Download Dataset 1 as CSV",
                data=dataset_contacts.to_csv(index=False).encode("utf-8"),
                file_name="dataset_1_direct_contacts.csv",
                mime="text/csv",
                use_container_width=True,
            )
            buf1 = io.BytesIO()
            with pd.ExcelWriter(buf1, engine="openpyxl") as writer:
                dataset_contacts.to_excel(writer, index=False, sheet_name="Contacts")
            c2.download_button(
                label="Download Dataset 1 as Excel",
                data=buf1.getvalue(),
                file_name="dataset_1_direct_contacts.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with tab2:
            st.subheader("LinkedIn Profiles")
            st.caption("Only rows with a valid LinkedIn profile URL. Deduplicated by unique profile link.")
            st.dataframe(dataset_linkedin.head(50), use_container_width=True)

            c3, c4 = st.columns(2)
            c3.download_button(
                label="Download Dataset 2 as CSV",
                data=dataset_linkedin.to_csv(index=False).encode("utf-8"),
                file_name="dataset_2_linkedin_leads.csv",
                mime="text/csv",
                use_container_width=True,
            )
            buf2 = io.BytesIO()
            with pd.ExcelWriter(buf2, engine="openpyxl") as writer:
                dataset_linkedin.to_excel(writer, index=False, sheet_name="LinkedInLeads")
            c4.download_button(
                label="Download Dataset 2 as Excel",
                data=buf2.getvalue(),
                file_name="dataset_2_linkedin_leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
