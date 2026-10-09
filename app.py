import io
import re
import pandas as pd
import phonenumbers
import streamlit as st

# Comprehensive list of reputable consumer, business, enterprise, and regional domains
PREFERRED_DOMAINS = [
    # Top Consumer & Enterprise Workspace
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
    # Major Telecom & ISP Providers
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
    # Regional & International Webmail
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

PREFERRED_DOMAINS_SET = set(PREFERRED_DOMAINS)

DISPOSABLE_DOMAINS = {
    "tempmail.com",
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
}

# Common variations of column names in raw recruitment and sourcing exports
COLUMN_ALIASES = {
    "first_name": ["first name", "firstname", "first", "fname", "given name"],
    "last_name": ["last name", "lastname", "last", "lname", "surname", "family name"],
    "full_name": ["full name", "fullname", "name", "contact name", "candidate name", "person name"],
    "email": ["email", "e-mail", "email address", "mail", "contact email", "primary email"],
    "phone": ["phone", "phone number", "mobile", "mobile number", "cell", "contact number", "telephone"],
    "location": ["location", "city", "address", "state", "candidate location", "current location", "metro"],
    "current_company": ["current company", "company", "organization", "employer", "current employer", "firm"],
    "linkedin_url": [
        "profile url",
        "profile_url",
        "profile link",
        "profilelink",
        "profile",
        "person linkedin url",
        "linkedin url",
        "linkedin_url",
        "linkedin profile",
        "linkedin",
        "candidate linkedin",
        "social url",
        "public profile url",
        "url",
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
    """Finds matching column names in the uploaded DataFrame based on predefined aliases."""
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
    """Extracts valid emails and prioritizes established providers and clean corporate domains."""
    if pd.isna(val):
        return None
    val_str = str(val).lower()

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", val_str)
    if not emails:
        return None

    clean_emails = [e for e in emails if e.split("@")[-1] not in DISPOSABLE_DOMAINS]
    pool = clean_emails if clean_emails else emails

    # 1. First priority: Known preferred webmail/workspace provider
    for email in pool:
        domain = email.split("@")[-1]
        if domain in PREFERRED_DOMAINS_SET:
            return email

    # 2. Second priority: Standard corporate/business domain
    for email in pool:
        domain = email.split("@")[-1]
        if domain not in DISPOSABLE_DOMAINS:
            return email

    # 3. Fallback
    return pool[0]


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
    """Extracts and normalizes any valid LinkedIn URL or handle."""
    if pd.isna(val):
        return None
    val_str = str(val).strip()

    if not val_str or val_str.lower() in ["nan", "none", "n/a", ""]:
        return None

    # Handle standard URLs and Sales Navigator links
    if "linkedin.com" in val_str.lower():
        cleaned = re.sub(r"\?.*$", "", val_str).strip().rstrip("/")
        if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
            cleaned = f"https://{cleaned}"
        return cleaned

    # Handle exported handles or vanity slugs
    if val_str.startswith("in/"):
        return f"https://www.linkedin.com/{val_str.strip().rstrip('/')}"

    return None


def clean_dataframe(df_raw: pd.DataFrame, region: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Extracts target fields, normalizes names/contacts, drops invalid rows, and dedupes."""
    mapping = map_columns(df_raw)
    base_df = pd.DataFrame()

    target_keys = ["first_name", "last_name", "full_name", "email", "phone", "location", "current_company", "linkedin_url"]
    for target in target_keys:
        src_col = mapping.get(target)
        if src_col and src_col in df_raw.columns:
            base_df[target] = df_raw[src_col]
        else:
            base_df[target] = None

    # Robust fallback for LinkedIn URL if alias mapping was skipped
    if base_df["linkedin_url"].isna().all():
        for col in df_raw.columns:
            col_str = str(col).lower()
            if "profile" in col_str or "linkedin" in col_str:
                base_df["linkedin_url"] = df_raw[col]
                break
            # Check content for linkedin.com occurrences
            sample = df_raw[col].dropna().astype(str).str.lower()
            if sample.str.contains("linkedin.com").any():
                base_df["linkedin_url"] = df_raw[col]
                break

    # Name Resolution: Split Full Name if separate First/Last fields are missing
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

    # Clean text columns
    for col in ["first_name", "last_name", "location", "current_company"]:
        base_df[col] = base_df[col].astype(str).str.strip()
        base_df[col] = base_df[col].replace({"nan": None, "None": None, "": None})

    # Standardize contact values
    base_df["email"] = base_df["email"].apply(extract_best_email)
    base_df["phone"] = base_df["phone"].apply(lambda p: format_phone_number(p, default_region=region))
    base_df["linkedin_url"] = base_df["linkedin_url"].apply(clean_linkedin_url)

    # --- DATASET 1: Verified Direct Contacts (Requires Email AND Phone) ---
    df1 = base_df.dropna(subset=["email", "phone"]).copy()
    initial_d1 = len(df1)
    df1 = df1.drop_duplicates(subset=["email"], keep="first")
    df1 = df1.drop_duplicates(subset=["phone"], keep="first")
    df1 = df1[["first_name", "last_name", "email", "phone", "location", "current_company"]]
    df1.columns = ["First Name", "Last Name", "Email", "Phone", "Location", "Current Company"]

    # --- DATASET 2: LinkedIn Sourcing Leads (Requires LinkedIn URL) ---
    df2 = base_df.dropna(subset=["linkedin_url"]).copy()
    initial_d2 = len(df2)
    df2 = df2.drop_duplicates(subset=["linkedin_url"], keep="first")
    df2 = df2[["first_name", "last_name", "location", "current_company", "linkedin_url"]]
    df2.columns = ["First Name", "Last Name", "Location", "Current Company", "LinkedIn URL"]

    stats = {
        "raw_total": len(df_raw),
        "d1_initial": initial_d1,
        "d1_final": len(df1),
        "d2_initial": initial_d2,
        "d2_final": len(df2),
    }

    return df1, df2, stats


# --- STREAMLIT USER INTERFACE ---
st.set_page_config(page_title="Contact & Lead Data Scrubber", page_icon="⚡", layout="wide")

st.title("Contact & Lead Data Scrubber")
st.caption("Upload multiple raw CSVs to automatically clean names, format contact information, and output two deduplicated datasets.")

with st.sidebar:
    st.header("Settings")
    selected_region = st.selectbox(
        "Default Phone Region",
        options=["US", "IN", "GB", "CA", "AU"],
        index=0,
        help="Used to format numbers that lack a country prefix.",
    )
    st.markdown("---")
    st.markdown("### Output Rules")
    st.markdown("**Dataset 1 (Direct Outreach):**")
    st.markdown("- Must contain both a valid Email and Phone")
    st.markdown("- Filters out throwaway emails, prioritizes trusted providers")
    st.markdown("- Deduplicated by email and phone")
    st.markdown("**Dataset 2 (LinkedIn Profiles):**")
    st.markdown("- Must contain a valid Profile URL or handle")
    st.markdown("- Standardized to full LinkedIn address")
    st.markdown("- Deduplicated by unique profile link")

uploaded_files = st.file_uploader(
    "Choose CSV files",
    type=["csv"],
    accept_multiple_files=True,
    help="Select one or more raw CSV candidate/lead exports.",
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

        with st.spinner("Processing files, normalizing data, and deduplicating..."):
            dataset_contacts, dataset_linkedin, stats = clean_dataframe(combined_raw, region=selected_region)

        col1, col2, col3 = st.columns(3)
        col1.metric("Raw Rows Uploaded", f"{stats['raw_total']:,}")
        col2.metric("Dataset 1 (Email + Phone)", f"{stats['d1_final']:,}")
        col3.metric("Dataset 2 (LinkedIn Leads)", f"{stats['d2_final']:,}")

        # Consolidated Multi-Tab Excel Workbook
        master_excel = io.BytesIO()
        with pd.ExcelWriter(master_excel, engine="openpyxl") as writer:
            dataset_contacts.to_excel(writer, index=False, sheet_name="Direct_Contacts")
            dataset_linkedin.to_excel(writer, index=False, sheet_name="LinkedIn_Profiles")

        st.download_button(
            label="Download Complete Excel Package (Both Datasets in Separate Sheets)",
            data=master_excel.getvalue(),
            file_name="cleaned_candidates_complete.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        tab1, tab2 = st.tabs(["Dataset 1: Phone & Email Contacts", "Dataset 2: LinkedIn Leads"])

        with tab1:
            st.subheader("Verified Direct Contacts")
            st.caption("Rows containing both a valid Phone Number and an Email address. Kept unique per person.")
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
            st.subheader("LinkedIn Leads")
            st.caption("Rows containing a valid Profile URL or LinkedIn link. Deduplicated by profile link.")
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
