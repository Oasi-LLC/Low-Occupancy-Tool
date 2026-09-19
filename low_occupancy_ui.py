import io
import streamlit as st
import pandas as pd
import datetime

from utils.backend_interface import get_available_properties
from export_low_occupancy_dates import export_low_occupancy_dates, ACCELERATOR_PROPERTIES

st.set_page_config(page_title="Low Occupancy Accelerator Dates", layout="wide")

st.title("Low Occupancy Accelerator Dates")

# Inputs
available_props = get_available_properties() or []
_default_prop_order = ("onera", "wb1", "lafavezion")
default_props = [p for p in _default_prop_order if p in available_props] or available_props

with st.expander("Controls", expanded=True):
    input_col1, input_col2, input_col3 = st.columns([2, 2, 2])
    with input_col1:
        property_selection = st.multiselect("Properties", available_props, default=default_props)
    with input_col2:
        lookahead_days = st.number_input("Booking window (days)", min_value=7, max_value=365, value=60, step=1)
    with input_col3:
        threshold_mode = st.radio("Threshold mode", ["auto", "manual"], index=0, horizontal=True)
        manual_threshold = None
        if threshold_mode == "manual":
            manual_threshold = st.number_input("Manual threshold (%)", min_value=1.0, max_value=100.0, value=40.0, step=1.0)
    
    aux_col1, aux_col2 = st.columns([2, 2])
    with aux_col1:
        force_fresh_pull = st.checkbox("Force fresh pl_daily pull (override 5h skip)", value=False)
    with aux_col2:
        skip_pull = st.checkbox("Skip pulling pl_daily", value=False)
    
    run_clicked = st.button("Run scan", type="primary")

if run_clicked:
    if not property_selection:
        st.error("Please select at least one property.")
    else:
        with st.spinner("Running low occupancy scan..."):
            result = export_low_occupancy_dates(
                property_selection=property_selection,
                output_file=None,  # no CSV writes by default
                pull_fresh_data=not skip_pull,
                lookahead_days=lookahead_days,
                threshold_mode=threshold_mode,
                manual_threshold=manual_threshold,
                force_fresh_pull=force_fresh_pull,
                verbose=False,
            )
        
        if not result:
            st.info("No qualifying dates found.")
        else:
            threshold_used = result["threshold_used"]
            fallback_used = result["fallback_used"]
            date_summary = result["date_summary"]
            date_sets = result["date_sets"]

            special_case_note = ""
            # if "azulik1" in property_selection:
            #     special_case_note = " (azulik1: Sun-Thu only, May onwards)"
            
            st.success(
                f"Completed. Threshold used: {threshold_used}%"
                + (" (fallback to 60%)" if fallback_used else "")
                + special_case_note
            )

            # Group date sets by property for display
            date_sets_by_prop = {}
            for ds in date_sets:
                date_sets_by_prop.setdefault(ds["property"], []).append(ds)

            tabs = st.tabs(property_selection)
            for tab, prop in zip(tabs, property_selection):
                with tab:
                    st.subheader(f"{prop}")
                    prop_summary = date_summary[date_summary["Property"] == prop]
                    weekday_label = (
                        "Sun–Thu, occ < threshold"
                        if prop in ACCELERATOR_PROPERTIES
                        else "Mon–Wed, occ < threshold"
                    )
                    if prop == "lafavezion":
                        weekday_label += "; Aug 2026 Fri–Sat included"
                    st.markdown(f"**Per-day summary ({weekday_label})**")
                    if prop in ACCELERATOR_PROPERTIES:
                        note = (
                            "ℹ️ Accelerator: today + 60 days; Sun–Thu; "
                            "occupancy < 40% per property, or < 60% if that property has fewer than 6 date sets"
                        )
                        if prop == "lafavezion":
                            note += "; all August 2026 Fri–Sat included"
                        st.info(note)
                    st.dataframe(prop_summary, hide_index=True, use_container_width=True)

                    if prop in date_sets_by_prop:
                        ds_rows = []
                        for idx, ds in enumerate(date_sets_by_prop[prop], start=1):
                            if ds["start_date"] == ds["end_date"]:
                                date_range = f"{ds['start_date']}"
                            else:
                                date_range = f"{ds['start_date']} – {ds['end_date']}"
                            ds_rows.append({
                                "Set": f"Set-{idx}",
                                "Date Range": date_range,
                                "Days": ds["days"],
                                "Avg Occupancy %": round(ds["avg_occ"], 2),
                            })
                        ds_df = pd.DataFrame(ds_rows)
                        weekday_label = (
                            "Sun–Thu, occ < threshold"
                            if prop in ACCELERATOR_PROPERTIES
                            else "Mon–Wed, occ < threshold"
                        )
                        if prop == "lafavezion":
                            weekday_label += "; Aug 2026 Fri–Sat included"
                        st.markdown(f"**Date sets (consecutive {weekday_label})**")
                        st.dataframe(ds_df, hide_index=True, use_container_width=True)
                        csv_bytes = ds_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "Export date sets as CSV",
                            data=csv_bytes,
                            file_name=f"{datetime.date.today().strftime('%Y-%m-%d')}_{prop}_export.csv",
                            mime="text/csv",
                            key=f"download_date_sets_{prop}",
                        )
                    else:
                        st.info("No date sets for this property.")


