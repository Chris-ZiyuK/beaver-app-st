import streamlit as st
import seaborn as sns
import streamlit.components.v1 as components
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import matplotlib.pyplot as plt
import geemap.foliumap as geemap
from streamlit_folium import folium_static
from scipy.stats import gaussian_kde
from sklearn.metrics import roc_curve, auc, accuracy_score
from service.Sentinel2_functions import process_Sentinel2_with_cloud_coverage
from service.Export_dam_imagery import  S2_PixelExtraction_Export,Sentinel_Only_Export
from service.Negative_sample_functions import deduplicate_locations, prepareHydro,sampleNegativePoints
from service.Parser import upload_points_to_ee, set_id_year_property
from service.Visualize_trends import S2_Export_for_visual, compute_all_metrics,compute_lst,add_landsat_lst, add_landsat_lst_et,compute_all_metrics_up_downstream, S2_Export_for_visual_flowdir, compute_all_metrics_LST_ET
from service.Data_management import set_id_negatives, add_dam_buffer_and_standardize_date
import ee 
import csv
import io
import os
import numpy as np
import pandas as pd
# import gdal
import tempfile
import rasterio

# st.set_page_config(layout="wide")

import json
from google.oauth2 import service_account

credentials_info = {
    "type": st.secrets["gcp_service_account"]["type"],
    "project_id": st.secrets["gcp_service_account"]["project_id"],
    "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
    "private_key": st.secrets["gcp_service_account"]["private_key"],
    "client_email": st.secrets["gcp_service_account"]["client_email"],
    "client_id": st.secrets["gcp_service_account"]["client_id"],
    "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
    "token_uri": st.secrets["gcp_service_account"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"],
    "universe_domain": st.secrets["gcp_service_account"]["universe_domain"]
}

credentials = service_account.Credentials.from_service_account_info(
    credentials_info,
    scopes=["https://www.googleapis.com/auth/earthengine"]
)

ee.Initialize(credentials, project="ee-beaver-lab")



# Initialize session state variables
if "Positive_collection" not in st.session_state:
    st.session_state.Positive_collection = None



# Streamlit UI
st.title("Analyzing the Impact of Beaver Dams")

# Section: Upload Points
st.header("Upload Dam Locations")
st.write(
    "The points must contain the following properties: longitude, latitude, Dam (positive or negative), date (YYYY-MM-DD), DamID."
)

# File upload
uploaded_file = st.file_uploader("Choose a CSV or GeoJSON file", type=["csv", "geojson"],key="Dam_file_uploader")

if uploaded_file:
    # feature_collection = upload_points_to_ee(uploaded_file)
    feature_collection = upload_points_to_ee(uploaded_file, widget_prefix="Dam")
    if feature_collection:
        st.session_state.Positive_collection = feature_collection  # Save to session state
        st.session_state['Full_positive'] = st.session_state.Positive_collection

if 'Full_positive' in st.session_state:
        Positives_map = geemap.Map()
        Positives_map.add_basemap("SATELLITE")
        Positives_map.centerObject(st.session_state['Full_positive'])
        Positives_map.addLayer(st.session_state['Full_positive'],{'color': 'blue'},'Dams')

        st.write("Dam Locations (blue points):")
        Positives_map.to_streamlit(width=1200, height=700)
        
        # st.write("Standardized Feature Collection:")
        # st.json(geemap.ee_to_geojson(feature_collection))


# Section: Draw Points
# st.subheader("Draw Points (optional)")
# enable_drawing = st.checkbox("Enable drawing on the map")

# # Initialize map
# map_center = [39.7538, -98.4439]
# draw_map = folium.Map(location=map_center, zoom_start=4)

# folium.TileLayer(
#     tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
#     attr="Esri",
#     name="Esri Satellite",
#     overlay=False,
#     control=True,
# ).add_to(draw_map)

# # Add uploaded points to the map
# if st.session_state.Positive_collection:
#     geojson_layer = geemap.ee_to_geojson(st.session_state.Positive_collection)
#     folium.GeoJson(geojson_layer, name="Uploaded Points").add_to(draw_map)

# # Add drawing functionality if enabled
# if enable_drawing:
#     draw = Draw(
#         export=True,
#         filename="points.geojson",
#         draw_options={
#             "rectangle": False,
#             "polygon": False,
#             "circle": False,
#             "polyline": False,
#             "marker": True,  # Enable marker tool for points
#         },
#         edit_options={"remove": True},
#     )
#     draw.add_to(draw_map)

# folium.LayerControl().add_to(draw_map)
# st_data = st_folium(draw_map, width=1200, height=700, key="main_map")

# # Process drawn points and append to points list
# points_list = []
# if enable_drawing and st_data and "all_drawings" in st_data:
#     geojson_list = st_data["all_drawings"]
#     if geojson_list:
#         for geojson in geojson_list:
#             if geojson and "geometry" in geojson:
#                 coordinates = geojson["geometry"]["coordinates"]
#                 points_list.append(coordinates)




# if points_list:
#     ee_points = ee.FeatureCollection(
#         [ee.Feature(ee.Geometry.Point(coord), {"id": idx}) for idx, coord in enumerate(points_list)]
#     )
#     if st.session_state.Positive_collection:
#         st.session_state.Positive_collection = st.session_state.Positive_collection.merge(ee_points)
#     else:
#         st.session_state.Positive_collection = ee_points
if "selected_waterway" not in st.session_state:
    st.session_state.selected_waterway = None  # Selected hydro dataset
if "dataset_loaded" not in st.session_state:
    st.session_state.dataset_loaded = False  # Track if a waterway dataset is loaded



if 'Full_positive' in st.session_state:
    st.header("Select Waterway")
    upload_own_checkbox = st.checkbox("Upload Own Dataset")
    choose_existing_checkbox = st.checkbox("Choose an Existing Dataset")

    if upload_own_checkbox:
        asset_id = st.text_input("Enter the GEE Asset Table ID for your dataset (e.g., projects/ee-beaver-lab/assets/Hydro/MA_Hydro_arc):")
        if st.button("Load Uploaded Dataset"):
            try:
                waterway_own = ee.FeatureCollection(asset_id)
                st.session_state.selected_waterway = waterway_own
                st.session_state.dataset_loaded = True
                st.success("Uploaded dataset loaded and added to the map.")
            except Exception as e:
                st.error(f"Failed to load the dataset. Error: {e}")

    if choose_existing_checkbox:
        positive_dam_bounds = st.session_state['Full_positive'].geometry().bounds()
        states_dataset = ee.FeatureCollection("TIGER/2018/States")  # US States boundaries dataset
        states_with_dams = states_dataset.filterBounds(positive_dam_bounds)
        st.session_state['Positive_dam_state'] = states_with_dams
        states_geo = st.session_state['Positive_dam_state']
        state_names = states_geo.aggregate_array("NAME").getInfo()

        if not state_names:
            st.error("No states found within the Dam data bounds.")
        else:
            st.write(f"States within Dam data bounds: {state_names}")

        # Dropdown for dataset options
        dataset_option = st.selectbox(
            "Choose a dataset for waterways:",
            ["Choose", "WWF Free Flowing Rivers", "NHD by State"]
        )

        # Button to confirm dataset selection
        if st.button("Load Existing Dataset"):
            try:
                if dataset_option == "WWF Free Flowing Rivers":
                    wwf_dataset = ee.FeatureCollection("WWF/HydroSHEDS/v1/FreeFlowingRivers")
                    clipped_wwf = wwf_dataset.filterBounds(states_with_dams)
                    st.session_state.selected_waterway = clipped_wwf
                    st.session_state.dataset_loaded = True
                    st.success("WWF dataset loaded and added to the map.")

                elif dataset_option == "NHD by State":
                    state_initials = {
                        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
                        "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
                        "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
                        "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
                        "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
                        "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
                        "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
                        "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
                        "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
                        "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
                        "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
                    }

                    nhd_collections = []
                    for state in state_names:
                        state_initial = state_initials.get(state)
                        if state_initial:
                            nhd_dataset = ee.FeatureCollection(
                                f'projects/sat-io/open-datasets/NHD/NHD_{state_initial}/NHDFlowline'
                            )
                            nhd_collections.append(nhd_dataset)

                    # Merge all NHD datasets
                    if nhd_collections:
                        merged_nhd = ee.FeatureCollection(nhd_collections).flatten()
                        st.session_state.selected_waterway = merged_nhd
                        st.session_state['Waterway'] = st.session_state.selected_waterway
                        st.session_state.dataset_loaded = True
                        st.success("NHD datasets for selected states loaded and added to the map.")
                    else:
                        st.error("No NHD datasets found for the selected states.")
            except Exception as e:
                st.error(f"Failed to load the dataset. Error: {e}")

    # Display the map
    if 'Waterway' in st.session_state:
        Waterway_map = geemap.Map()
        Waterway_map.add_basemap("SATELLITE")
        Waterway_map.centerObject(st.session_state['Full_positive'])
        Waterway_map.addLayer(st.session_state['Full_positive'],{'color': 'FF0000'},'Dams')
        Waterway_map.addLayer(st.session_state.selected_waterway, {"color": "blue"}, "Selected Waterway")
        Waterway_map.to_streamlit(width=1200, height=700)



# Combined Dam Status and Buffering Section
if "Combined_collection" not in st.session_state:
    st.session_state.Combined_collection = None
        # st.session_state.Positive_collection = feature_collection


# Step 1: Upload Waterway
if 'Waterway' in st.session_state:
    # st.header("Upload Waterway")
    st.header("Upload or Generate Non-Dam Locations")
    upload_negatives_checkbox = st.checkbox("Upload Non-Dam Dataset (must be on a waterbody)")
    generate_negatives_checkbox = st.checkbox("Generate Non-Dam Locations")

    if upload_negatives_checkbox:
        uploaded_negatives_file = st.file_uploader("Choose a CSV or GeoJSON file", type=["csv", "geojson"],key="Non_Dam_file_uploader")
        if uploaded_negatives_file:
            # negative_feature_collection = upload_points_to_ee(uploaded_negatives_file)
            negative_feature_collection = upload_points_to_ee(uploaded_negatives_file,widget_prefix="NonDam")
            st.success("Locations uploaded!")
            if negative_feature_collection:
                st.session_state.Negative_upload_collection = negative_feature_collection  # Save to session state
                st.session_state['Full_negative'] = st.session_state.Negative_upload_collection

                first_pos = st.session_state.Positive_collection.first()
                date = ee.Date(first_pos.get('date'))
                year_string = date.format('YYYY')
                full_date = ee.String(year_string).cat('-07-01')
            
                negativePoints = negative_feature_collection.map(lambda feature: feature.set('Dam', 'negative').set("date",full_date))
                
                fc = negativePoints
                features_list = fc.toList(fc.size())
                indices = ee.List.sequence(0, fc.size().subtract(1))
                
                def set_id_negatives2(idx):
                    idx = ee.Number(idx)
                    feature = ee.Feature(features_list.get(idx))
                    # Cast idx.add(1) to an integer and then format as a string without decimals.
                    labeled_feature = feature.set(
                        'id_property', ee.String('N').cat(idx.add(1).int().format())
                    )
                    return labeled_feature
                Neg_points_id = ee.FeatureCollection(indices.map(set_id_negatives2))

                Pos_collection = st.session_state.Positive_collection
                Pos_collection = Pos_collection.map(lambda feature: feature.set('Dam', 'positive'))

                pos_features_list = Pos_collection.toList(Pos_collection.size())
                pos_indices = ee.List.sequence(0, Pos_collection.size().subtract(1))

                def set_id_positives(idx):
                    idx = ee.Number(idx)
                    feature = ee.Feature(pos_features_list.get(idx))
                    labeled_feature = feature.set(
                        'id_property', ee.String('P').cat(idx.add(1).int().format())
                    )
                    return labeled_feature

                Positive_dam_id = ee.FeatureCollection(pos_indices.map(set_id_positives))

                # Positive_Dams = st.session_state.Positive_collection
                # Positive_dam_id = Positive_Dams.map(lambda feature: feature.set('Dam', 'positive'))
                # Positive_dam_id = Positive_dam_id
                Merged_collection = Positive_dam_id.merge(Neg_points_id)
                st.session_state['Merged_collection'] = Merged_collection

                Negatives_map = geemap.Map()
                Negatives_map.add_basemap("SATELLITE")
                Negatives_map.addLayer(negativePoints,{'color': 'red', 'width': 2},'Negative')
                Negatives_map.addLayer(Positive_dam_id,{'color': 'blue'},'Positive')
                Negatives_map.centerObject(Merged_collection)
                Negatives_map.to_streamlit(width=1200, height=700)

            



    if generate_negatives_checkbox:
        st.subheader("Specify the parameters for negative point generation:")

        # User inputs for buffer radii & sampling scale
        innerRadius = st.number_input("Inner Radius (meters)", value=500, min_value=0, step=50)
        outerRadius = st.number_input("Outer Radius (meters)", value=5000, min_value=0, step=100)
        samplingScale = st.number_input("Sampling Scale (meters)", value=10, min_value=1, step=1)
        
        # Input for the date year
        if st.button("Generate Negative Points"):
            with st.spinner("Generating negative points..."):
                # 1) Deduplicate Positive Dams and get centroids
                first_pos = st.session_state.Positive_collection.first()
                date = ee.Date(first_pos.get('date'))
                year_string = date.format('YYYY')
                full_date = ee.String(year_string).cat('-07-01')
            

                positive_dams_fc = deduplicate_locations(st.session_state.Positive_collection)
                
                # 2) Convert waterway feature collection to a raster mask
                waterway_fc = st.session_state.selected_waterway  # The loaded hydro dataset
                hydroRaster = prepareHydro(waterway_fc)
                
                # 3) Sample negative points
                negativePoints = sampleNegativePoints(
                    positive_dams_fc, 
                    hydroRaster, 
                    innerRadius, 
                    outerRadius, 
                    samplingScale
                )
                negativePoints = negativePoints.map(lambda feature: feature.set('Dam', 'negative').set("date",full_date))
                
                fc = negativePoints
                features_list = fc.toList(fc.size())
                indices = ee.List.sequence(0, fc.size().subtract(1))
                # Step 3: Map over the indices to get each feature and set a new property.
                

                def set_id_negatives2(idx):
                    idx = ee.Number(idx)
                    feature = ee.Feature(features_list.get(idx))
                    # Cast idx.add(1) to an integer and then format as a string without decimals.
                    labeled_feature = feature.set(
                        'id_property', ee.String('N').cat(idx.add(1).int().format())
                    )
                    return labeled_feature
                
                Neg_points_id = ee.FeatureCollection(indices.map(set_id_negatives2))
                
                Pos_collection = st.session_state.Positive_collection
                Pos_collection = Pos_collection.map(lambda feature: feature.set('Dam', 'positive'))

                pos_features_list = Pos_collection.toList(Pos_collection.size())
                pos_indices = ee.List.sequence(0, Pos_collection.size().subtract(1))

                def set_id_positives(idx):
                    idx = ee.Number(idx)
                    feature = ee.Feature(pos_features_list.get(idx))
                    labeled_feature = feature.set(
                        'id_property', ee.String('P').cat(idx.add(1).int().format())
                    )
                    return labeled_feature

                Positive_dam_id = ee.FeatureCollection(pos_indices.map(set_id_positives))
                # Positive_Dams = st.session_state.Positive_collection
                # Positive_dam_id = Positive_Dams.map(lambda feature: feature.set('Dam', 'positive').set('id_property', feature.get('DamID')))
                Merged_collection = Positive_dam_id.merge(Neg_points_id)
                st.session_state['Merged_collection'] = Merged_collection

                Negative_points = geemap.Map()
                Negative_points.add_basemap("SATELLITE")
                Negative_points.addLayer(negativePoints,{'color': 'red', 'width': 2},'Negative')
                Negative_points.addLayer(Positive_dam_id,{'color': 'blue'},'Positive')
                Negative_points.centerObject(Merged_collection)
                Negative_points.to_streamlit(width=1200, height=700)
        

if "buffer_radius" not in st.session_state:
    st.session_state.buffer_radius = 200
if "year_selection" not in st.session_state:
    st.session_state.year_selection = 2020

if 'Merged_collection' in st.session_state:
    st.header("Merge and Buffer Dam and Non Dam locations:")

    # User inputs for Dam status and buffer radius
    buffer_radius = st.number_input(
        "Enter buffer radius (meters):", min_value=1, step=1, value=st.session_state.buffer_radius
    )

    # Button to apply Dam status and create buffers
    if st.button("Apply Dam Status and Create Buffers"):
        # Apply the function to the feature collection

        first_pos = st.session_state.Positive_collection.first()
        date = ee.Date(first_pos.get('date'))
        year_string = date.format('YYYY')
        full_date = ee.String(year_string).cat('-07-01')


        def add_dam_buffer_and_standardize_date(feature):
            # Add Dam property and other metadata
            dam_status = feature.get("Dam")
            
            # Force the date to July 1st of the specified year
            standardized_date = date
            formatted_date = date.format('YYYYMMdd')
            
            # Buffer geometry while retaining properties
            buffered_geometry = feature.geometry().buffer(buffer_radius)
            
            # Create a new feature with buffered geometry and updated properties
            return ee.Feature(buffered_geometry).set({
                "Dam": dam_status,
                "Survey_Date": standardized_date,  # Set survey date to July 1st
                "Damdate": ee.String("DamDate_").cat(formatted_date),  # Updated date format
                "Point_geo": feature.geometry(),
                "id_property": feature.get("id_property")
            })


        Buffered_collection = st.session_state['Merged_collection'].map(add_dam_buffer_and_standardize_date)
        

        # Select only relevant properties
        Dam_data = Buffered_collection.select(['id_property', 'Dam', 'Survey_Date', 'Damdate', 'Point_geo'])
        # Dam_data = Buffered_collection.select(['Dam', 'Survey_Date', 'Damdate', 'Point_geo'])

        # Save to session state
        st.session_state['Dam_data'] = Dam_data

        st.success(f"Buffers created with radius {buffer_radius} meters.")

if 'Dam_data' in st.session_state:
    st.write("Buffered Feature Collection:")
    dam_bounds = st.session_state['Dam_data'].geometry().bounds()
    states_dataset = ee.FeatureCollection("TIGER/2018/States")  # US States boundaries dataset
    states_with_dams = states_dataset.filterBounds(dam_bounds)
    st.session_state['Dam_state'] = states_with_dams
    Dam_data = st.session_state['Dam_data']
    Negative = Dam_data.filter(ee.Filter.eq('Dam', 'negative'))
    Positive = Dam_data.filter(ee.Filter.eq('Dam', 'positive'))

    Buffer_map = geemap.Map()
    Buffer_map.add_basemap("SATELLITE")
    # Buffer_map.addLayer(st.session_state['Dam_data'], {"color": "blue"}, "Buffered Points")
    Buffer_map.addLayer(Negative,{'color': 'red'},'Negative')
    Buffer_map.addLayer(Positive,{'color': 'blue'},'Positive')
    Buffer_map.centerObject(st.session_state['Dam_data'])
    Buffer_map.to_streamlit(width=800, height=600)
    st.header("Visualize trends")
    if st.button("Visualize Trends"):
        Initiate_visualize = 'visualize' 
        st.session_state['Visualize_trends'] = Initiate_visualize

import io  # Make sure to import io for the BytesIO functionality

if 'Visualize_trends' in st.session_state:
    
    with st.spinner("Processing... this may take some time."):
        # Filter Imagery
        Dam_data = st.session_state['Dam_data']

        S2_cloud_mask_export = ee.ImageCollection(S2_Export_for_visual(Dam_data))
        S2_ImageCollection = ee.ImageCollection(S2_cloud_mask_export)

        S2_with_LST = S2_ImageCollection.map(add_landsat_lst_et)
        results_fc_lst = S2_with_LST.map(compute_all_metrics_LST_ET)       

        results_fcc_lst = ee.FeatureCollection(results_fc_lst)       

        ## Practice
        df_lst = geemap.ee_to_df(results_fcc_lst)
        st.success("Dataframe with NDVI, NDWI, LST, and ET generated!")

        # 4) Convert columns to numeric
        df_lst['Image_month'] = pd.to_numeric(df_lst['Image_month'])
        df_lst['Image_year'] = pd.to_numeric(df_lst['Image_year'])
        df_lst['Dam_status'] = df_lst['Dam_status'].replace({'positive': 'Dam', 'negative': 'Non-dam'})
        df_lst['LST'] = pd.to_numeric(df_lst['LST'])
        df_lst['ET'] = pd.to_numeric(df_lst['ET'])  # <--- NEW: Ensure ET is numeric

        # 5) Set up your plotting style (using a white background)
        sns.set(style="whitegrid", palette="muted")
        fig = plt.figure(figsize=(12, 18), facecolor='white', edgecolor='white')

        # 6) Sort the DataFrame by year, then month
        df_lst = df_lst.sort_values(by=['Image_year', 'Image_month'])

        ############################################
        # 1) Plot NDVI
        ############################################
        ax1 = fig.add_subplot(4, 1, 1)
        sns.lineplot(
            data=df_lst, 
            x="Image_month", 
            y="NDVI", 
            hue="Dam_status", 
            style="Dam_status",
            markers=True, 
            dashes=False,
            ax=ax1
        )
        ax1.set_title('NDVI by Month for Dam and Non-Dam Sites', fontsize=14, color='black')
        ax1.set_xlabel('Month', fontsize=12, color='black')
        ax1.set_ylabel('Mean NDVI', fontsize=12, color='black')
        ax1.legend(title='Dam Status', loc='upper right')
        ax1.set_xticks(range(1, 13))
        ax1.tick_params(axis='x', colors='black')
        ax1.tick_params(axis='y', colors='black')

        ############################################
        # 2) Plot NDWI_Green
        ############################################
        ax2 = fig.add_subplot(4, 1, 2)
        sns.lineplot(
            data=df_lst, 
            x="Image_month", 
            y="NDWI_Green", 
            hue="Dam_status", 
            style="Dam_status",
            markers=True, 
            dashes=False,
            ax=ax2
        )
        ax2.set_title('NDWI Green by Month for Dam and Non-Dam Sites', fontsize=14, color='black')
        ax2.set_xlabel('Month', fontsize=12, color='black')
        ax2.set_ylabel('Mean NDWI Green', fontsize=12, color='black')
        ax2.legend(title='Dam Status', loc='upper right')
        ax2.set_xticks(range(1, 13))
        ax2.tick_params(axis='x', colors='black')
        ax2.tick_params(axis='y', colors='black')

        ############################################
        # 3) Plot LST
        ############################################
        ax3 = fig.add_subplot(4, 1, 3)
        sns.lineplot(
            data=df_lst,
            x="Image_month",
            y="LST",
            hue="Dam_status",
            style="Dam_status",
            markers=True,
            dashes=False,
            ax=ax3
        )
        ax3.set_title('LST by Month for Dam and Non-Dam Sites', fontsize=14, color='black')
        ax3.set_xlabel('Month', fontsize=12, color='black')
        ax3.set_ylabel('Mean LST (°C)', fontsize=12, color='black')
        ax3.legend(title='Dam Status', loc='upper right')
        ax3.set_xticks(range(1, 13))
        ax3.tick_params(axis='x', colors='black')
        ax3.tick_params(axis='y', colors='black')

        ############################################
        # 4) Plot ET
        ############################################
        ax4 = fig.add_subplot(4, 1, 4)
        sns.lineplot(
            data=df_lst,
            x="Image_month",
            y="ET",
            hue="Dam_status",
            style="Dam_status",
            markers=True,
            dashes=False,
            ax=ax4
        )
        ax4.set_title('ET by Month for Dam and Non-Dam Sites', fontsize=14, color='black')
        ax4.set_xlabel('Month', fontsize=12, color='black')
        ax4.set_ylabel('Mean ET', fontsize=12, color='black')
        ax4.legend(title='Dam Status', loc='upper right')
        ax4.set_xticks(range(1, 13))
        ax4.tick_params(axis='x', colors='black')
        ax4.tick_params(axis='y', colors='black')

        # 7) Final layout adjustments and display
        fig.tight_layout()
        st.pyplot(fig)

        # 8) Provide a download button to export the figure as a PNG image
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        buf.seek(0)
        st.download_button(
            label="Download Figure",
            data=buf,
            file_name="trends_figure.png",
            mime="image/png"
        )
# if 'Visualize_trends' in st.session_state:
    
#     with st.spinner("Processing... this may take some time."):
#         # Filter Imagery
#         Dam_data = st.session_state['Dam_data']

#         S2_cloud_mask_export = ee.ImageCollection(S2_Export_for_visual(Dam_data))
#         S2_ImageCollection = ee.ImageCollection(S2_cloud_mask_export)

#         S2_with_LST = S2_ImageCollection.map(add_landsat_lst_et)
#         results_fc_lst = S2_with_LST.map(compute_all_metrics_LST_ET)       

#         results_fcc_lst = ee.FeatureCollection(results_fc_lst)       

#         ## Practice
#         df_lst = geemap.ee_to_df(results_fcc_lst)
#         st.success("Dataframe with NDVI, NDWI, LST, and ET generated!")

#         # 4) Convert columns to numeric
#         df_lst['Image_month'] = pd.to_numeric(df_lst['Image_month'])
#         df_lst['Image_year'] = pd.to_numeric(df_lst['Image_year'])
#         df_lst['LST'] = pd.to_numeric(df_lst['LST'])
#         df_lst['ET'] = pd.to_numeric(df_lst['ET'])  # <--- NEW: Ensure ET is numeric

#         # 5) Set up your plotting style
#         sns.set(style="whitegrid", palette="muted")
#         plt.figure(figsize=(12, 18), facecolor='none', edgecolor='none')

#         # 6) Sort the DataFrame by year, then month
#         df_lst = df_lst.sort_values(by=['Image_year', 'Image_month'])

#         ############################################
#         # 1) Plot NDVI
#         ############################################
#         plt.subplot(4, 1, 1)
#         sns.lineplot(
#             data=df_lst, 
#             x="Image_month", 
#             y="NDVI", 
#             hue="Dam_status", 
#             style="Dam_status",
#             markers=True, 
#             dashes=False
#         )
#         plt.title('NDVI by Month for Positive and Negative Sites', fontsize=14, color='white')
#         plt.xlabel('Month', fontsize=12, color='white')
#         plt.ylabel('Mean NDVI', fontsize=12, color='white')
#         plt.legend(title='Dam Status', loc='upper right')
#         plt.xticks(range(1, 13), color='white') 
#         plt.yticks(color='white') 

#         ############################################
#         # 2) Plot NDWI_Green
#         ############################################
#         plt.subplot(4, 1, 2)
#         sns.lineplot(
#             data=df_lst, 
#             x="Image_month", 
#             y="NDWI_Green", 
#             hue="Dam_status", 
#             style="Dam_status",
#             markers=True, 
#             dashes=False
#         )
#         plt.title('NDWI Green by Month for Positive and Negative Sites', fontsize=14, color='white')
#         plt.xlabel('Month', fontsize=12, color='white')
#         plt.ylabel('Mean NDWI Green', fontsize=12, color='white')
#         plt.legend(title='Dam Status', loc='upper right')
#         plt.xticks(range(1, 13), color='white')  
#         plt.yticks(color='white') 

#         ############################################
#         # 3) Plot LST
#         ############################################
#         plt.subplot(4, 1, 3)
#         sns.lineplot(
#             data=df_lst,
#             x="Image_month",
#             y="LST",
#             hue="Dam_status",
#             style="Dam_status",
#             markers=True,
#             dashes=False
#         )
#         plt.title('LST by Month for Positive and Negative Sites', fontsize=14, color='white')
#         plt.xlabel('Month', fontsize=12, color='white')
#         plt.ylabel('Mean LST (°C)', fontsize=12, color='white')
#         plt.legend(title='Dam Status', loc='upper right')
#         plt.xticks(range(1, 13), color='white')  
#         plt.yticks(color='white') 

#         ############################################
#         # 4) Plot ET
#         ############################################
#         plt.subplot(4, 1, 4)
#         sns.lineplot(
#             data=df_lst,
#             x="Image_month",
#             y="ET",
#             hue="Dam_status",
#             style="Dam_status",
#             markers=True,
#             dashes=False
#         )
#         plt.title('ET by Month for Positive and Negative Sites', fontsize=14, color='white')
#         plt.xlabel('Month', fontsize=12, color='white')
#         plt.ylabel('Mean ET', fontsize=12, color='white')
#         plt.legend(title='Dam Status', loc='upper right')
#         plt.xticks(range(1, 13), color='white')  
#         plt.yticks(color='white')

#         # 7) Final layout adjustments and display
#         plt.tight_layout()
#         plt.show()
#         st.pyplot(plt)
        


    # st.subheader("Upstream and Downstream Effects")
    # if st.button("Visualize Upstream and Downstream Effects"):
    #     with st.spinner("Processing upstream/downstream... please wait."):

    #         waterway_fc = st.session_state.selected_waterway  # The loaded hydro dataset
    #         S2_ImageCollection_flowdir = S2_Export_for_visual_flowdir(Dam_data,waterway_fc)
    #         # B) Add LST + OpenET
    #         S2_with_LST_ET_flowdir = S2_ImageCollection_flowdir.map(add_landsat_lst_et)
    #         # C) Compute separate up/down metrics
    #         results_fc_ET = S2_with_LST_ET_flowdir.map(compute_all_metrics_up_downstream)
    #         # D) Convert to DataFrame
    #         results_fcc_ET = ee.FeatureCollection(results_fc_ET)
    
    #         df_ET = geemap.ee_to_df(results_fcc_ET)
    #         st.success("Upstream/Downstream dataframe generated!")

    #         df_ET['Image_month'] = pd.to_numeric(df_ET['Image_month'], errors='coerce')
    #         df_ET['Image_year']  = pd.to_numeric(df_ET['Image_year'], errors='coerce')
    #         df_ET = df_ET.sort_values(by=['Image_year','Image_month']).reset_index(drop=True)

    #         sns.set(style="whitegrid")

    #         def melt_and_plot(df, metric, ax):
    #             """ Helper to melt Up/Down columns and plot in a single lineplot. """
    #             up_col = f"{metric}_up"
    #             down_col = f"{metric}_down"

    #             # Melt into long form
    #             melted = df.melt(
    #                 id_vars=['Image_year', 'Image_month', 'Dam_status'],
    #                 value_vars=[up_col, down_col],
    #                 var_name='Flow',
    #                 value_name=metric
    #             )
    #             # Rename Flow
    #             melted['Flow'] = melted['Flow'].replace({
    #                 up_col: 'Upstream',
    #                 down_col: 'Downstream'
    #             })

    #             # Seaborn lineplot
    #             sns.lineplot(
    #                 data=melted,
    #                 x='Image_month',
    #                 y=metric,
    #                 hue='Dam_status',
    #                 style='Flow',
    #                 markers=True,
    #                 dashes=False,
    #                 ax=ax
    #             )
    #             ax.set_title(f"{metric.upper()} by Month (Upstream vs Downstream)")

    #         # Plot NDVI, NDWI, LST, ET in 4 subplots
    #         fig, axes = plt.subplots(nrows=4, ncols=1, figsize=(10,16))
    #         melt_and_plot(df_ET, 'NDVI', axes[0])
    #         melt_and_plot(df_ET, 'NDWI', axes[1])
    #         melt_and_plot(df_ET, 'LST', axes[2])
    #         melt_and_plot(df_ET, 'ET', axes[3])
    #         plt.tight_layout()
    #         plt.show()
    #         st.pyplot(fig)

    #         # Display the flow direction map
    #         first = S2_ImageCollection_flowdir.first()
    #         buffered_geometry = ee.Geometry(first.get('Area'))
    #         point_geom = buffered_geometry.centroid()

    #         FlowDir = geemap.Map()
    #         FlowDir.add_basemap("SATELLITE")
    #         FlowDir.addLayer(first.select('upstream'), {'color': 'blue'}, 'Upstream')
    #         FlowDir.addLayer(first.select('downstream'), {'color': 'red'}, 'Downstream')
    #         FlowDir.addLayer(first.select('elevation'), {}, 'Elevation')
    #         FlowDir.addLayer(point_geom, {}, 'Center Point')
    #         FlowDir.centerObject(st.session_state['Dam_data'])
    #         FlowDir.to_streamlit(width=800, height=600)

# # # Ensure session state for selected datasets and workflow progression
# if "selected_datasets" not in st.session_state:
#     st.session_state.selected_datasets = {}  # Store datasets for further analysis



#     # # "Use this Waterway Map" button
#     if st.session_state.dataset_loaded:
#         if st.button("Use this Waterway Map"):
#             Initiate_analysis = 'initiate' 
#             st.session_state['Initiate_analysis'] = Initiate_analysis



# # Step 2: Dataset Selection and Visualization
# # Dataset IDs and their processing logic
# datasets = {
#     "CHIRPS Precipitation": {
#         "processing": lambda start, end, bounds: ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
#         .filterDate(start, end)
#         .filterBounds(bounds)
#         .mean()
#         .select('precipitation')
#         .rename('CHIRPS_precipitation_2yr_avg')
#         .clip(bounds),
#         "visualization": {"min": 1, "max": 17, "palette": ['001137', '0aab1e', 'e7eb05', 'ff4a2d', 'e90000']},
#     },
#     "ECMWF Precipitation": {
#         "processing": lambda start, end, bounds: ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_BY_HOUR")
#         .filterDate(start, end)
#         .filterBounds(bounds)
#         .mean()
#         .select("total_precipitation")
#         .rename("ECMWF_precipitation_2yr_avg")
#         .clip(bounds),
#         "visualization": {"min": 0, "max": 300, "palette": ["blue", "cyan", "green", "yellow", "red"]},
#     },
#     "Temperature": {
#         "processing": lambda start, end, bounds: ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_BY_HOUR")
#         .filterDate(start, end)
#         .filterBounds(bounds)
#         .mean()
#         .select('temperature_2m')
#         .rename('ECMWF_temperature_2m_2yr_avg')
#         .clip(bounds),
#         "visualization": {"min": 250, "max": 320, "palette": [
#             '000080', '0000d9', '4000ff', '8000ff', '0080ff', '00ffff',
#             '00ff80', '80ff00', 'daff00', 'ffff00', 'fff500', 'ffda00',
#             'ffb000', 'ffa400', 'ff4f00', 'ff2500', 'ff0a00', 'ff00ff',
#         ]},
#     },
#     "Surface Runoff": {
#         "processing": lambda start, end, bounds: ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_BY_HOUR")
#         .filterDate(start, end)
#         .filterBounds(bounds)
#         .mean()
#         .select("surface_runoff")
#         .rename("ECMWF_surface_runoff_2yr_avg")
#         .clip(bounds),
#         "visualization": {"min": 0, "max": 50, "palette": ["blue", "cyan", "green", "yellow", "red"]},
#     },
#     "Elevation": {
#         "processing": lambda start, end, bounds: ee.Image("USGS/3DEP/10m")
#         .select('elevation')
#         .rename('Elevation')
#         .clip(bounds),
#         "visualization": {"min": 0, "max": 3000, "palette": [
#             '3ae237', 'b5e22e', 'd6e21f', 'fff705', 'ffd611', 'ffb613', 'ff8b13',
#             'ff6e08', 'ff500d', 'ff0000', 'de0101', 'c21301', '0602ff', '235cb1',
#             '307ef3', '269db1', '30c8e2', '32d3ef', '3be285', '3ff38f', '86e26f'
#         ],},
#     },  
#     "Slope": {
#         "processing": lambda start, end, bounds: ee.Terrain.slope(ee.Image("USGS/3DEP/10m").select('elevation'))
#         .rename('Slope')
#         .clip(bounds),
#         "visualization": {"min": 0, "max": 60},
#     },
#     "Vegetation": {
#         "processing": lambda start, end, bounds: ee.Image("USGS/GAP/CONUS/2011")
#         .clip(bounds),
#         "visualization": {"bands":['landcover'],"min": 1, "max": 584},
#     },
# }

# # Function to extract the date range and geometry for the first dam
# def get_state_bounds_and_date_range():
#     if "Dam_data" not in st.session_state:
#         st.error("No dam data available.")
#         return None, None
#     dam_data = st.session_state["Dam_data"]
#     first_dam = dam_data.first()
#     image_date = ee.Date(first_dam.get("Survey_Date"))
#     start_date = image_date.advance(-6, 'month').format("YYYY-MM-dd")
#     end_date = image_date.advance(6, 'month').format("YYYY-MM-dd")
#     # Get state bounds
#     states_dataset = ee.FeatureCollection("TIGER/2018/States")
#     state_bounds = states_dataset.filterBounds(dam_data.geometry().bounds()).geometry()
#     return start_date, end_date, state_bounds

# if 'Initiate_analysis' in st.session_state:
#     st.header("Select Additional Datasets to Include")

#     start_date, end_date, state_bounds = get_state_bounds_and_date_range()
#     if not (start_date and end_date and state_bounds):
#         st.stop()

# # Checkboxes for dataset selection
#     st.write("Select datasets to include:")
#     for dataset_name in datasets.keys():
#         st.session_state.selected_datasets[dataset_name] = st.checkbox(
#             dataset_name,
#             value=st.session_state.selected_datasets.get(dataset_name, True),
#         )
#      # Map for Dataset Visualization
#     st.write("Visualize Dataset on the Map")
#     Dataset_Map = geemap.Map()
#     Dataset_Map.add_basemap("SATELLITE")

#     selected_dataset_name = st.selectbox("Choose a dataset to visualize:", ["Choose"] + list(datasets.keys()))
#     if selected_dataset_name != "Choose":
#         dataset = datasets[selected_dataset_name]["processing"](start_date, end_date, state_bounds)
#         vis_params = datasets[selected_dataset_name]["visualization"]
#         Dataset_Map.addLayer(dataset, vis_params, f"{selected_dataset_name} (Processed)")

#     # Display the map
#     Dataset_Map.centerObject(st.session_state["Dam_data"])
#     Dataset_Map.to_streamlit(width=1200, height=700)

#     # # "Use this Waterway Map" button
#     if st.button("Confirm Datasets"):
#         Confirm_datasets = 'confirm' 
#         st.session_state['Confirm_datasets'] = Confirm_datasets

# # Step 3: Filter Imagery per Dam
# if 'Confirm_datasets' in st.session_state:
#     st.success("Datasets confirmed. Proceeding to filter imagery.")
#     st.header("Filter Imagery per Dam")
#      # Button to start filtering process
#     if st.button("Run Filtering and Visualization Process"):
#         with st.spinner("Processing... this may take some time."):
#             # Filter Imagery
#             Dam_Collection = st.session_state['Dam_data']
#             One_dam = Dam_Collection.limit(2)
#             S2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
#             S2_cloud_filter = process_Sentinel2_with_cloud_coverage(S2)

#             selected_datasets = st.session_state.selected_datasets
#             Hydro = st.session_state.selected_waterway

#             ImageFilter = S2_PixelExtraction_Export(One_dam, S2_cloud_filter, Hydro, selected_datasets)
#             st.session_state['Single Image Collection'] = ImageFilter


# if 'Single Image Collection' in st.session_state:
#     Image_collection = st.session_state['Single Image Collection']
#     S2_filename_id = Image_collection.aggregate_array("Full_id").getInfo()
#     cloud_free_id = next((id for id in S2_filename_id if id.endswith("Cloud_0.0")), None)

#     if not cloud_free_id:
#                 st.error("No cloud-free images (Cloud_0.0) found in the collection.")
#     else:
#         specific_image = Image_collection.filter(ee.Filter.eq("Full_id", cloud_free_id)).first()
#         all_bands = specific_image.bandNames().getInfo()

#         # Define visualization options
#         visualization_options = {
#             "NDVI": specific_image.normalizedDifference(["S2_NIR", "S2_Red"]).rename("NDVI"),
#             "NDWI": specific_image.normalizedDifference(["S2_Green", "S2_NIR"]).rename("NDWI"),
#             "EVI": specific_image.expression(
#                 "2.5 * ((NIR - Red) / (NIR + 6 * Red - 7.5 * Blue + 1))",
#                 {"NIR": specific_image.select("S2_NIR"), "Red": specific_image.select("S2_Red"), "Blue": specific_image.select("S2_Blue")}
#             ).rename("EVI"),
#             "True Color (RGB)": specific_image.select(["S2_Red", "S2_Green", "S2_Blue"]),
#         }

#         # Combine bands and visualization options into a single dropdown
#         dropdown_options = all_bands + list(visualization_options.keys())
        
#         st.success("Processing complete!")
#         st.subheader("Visualize", divider='green')
#         selected_option = st.selectbox("Select a band or visualization type:", ["Choose"] + dropdown_options)

#         # Initialize map
#         Image_Map = geemap.Map()
#         Image_Map.add_basemap("SATELLITE")
#         Image_Map.centerObject(specific_image)

#         # Check the selected option
#         if selected_option != "Choose":
#             if selected_option in all_bands:
#                 vis_image = specific_image.select(selected_option)
#                 vis_params = {"min": 0, "max": 3000}  # Adjust based on the band's range
#             elif selected_option in visualization_options:
#                 vis_image = visualization_options[selected_option]
#                 vis_params = {"min": 0, "max": 1} if selected_option in ["NDVI", "NDWI", "EVI"] else {"min": 0, "max": 3000}
#             else:
#                 vis_image = None

#             if vis_image:
#                 Image_Map.addLayer(vis_image, vis_params, selected_option)

#         # Display the map
#         st.write("Image Visualization:")
#         Image_Map.to_streamlit(width=1200, height=700)



# if 'Single Image Collection' in st.session_state:
#     # Step 4: Export Images to Computer
#     st.subheader("Export", divider='green')

#     export_dir = st.text_input(
#         "Enter the folder path where you want to export the images. "
#         "Example (Windows): C:\\Users\\John\\Desktop\\ExportFolder. "
#         "Example (Mac/Linux): /home/yourusername/Documents/ExportFolder"
#     )
#    # Button to start export process
#     if st.button("Export Images"):
#         if not export_dir:
#             st.error("Please specify a folder path.")
#         else:
#             with st.spinner(f"Exporting images to {export_dir}... this may take some time."):
#                 try:
#                     # Split the Dam_Collection into smaller chunks
#                     Dam_Collection = st.session_state['Dam_data']
#                     num_chunks = 10  # Adjust based on your dataset size
#                     dam_list = Dam_Collection.toList(Dam_Collection.size())
#                     chunk_size = ee.Number(Dam_Collection.size()).divide(num_chunks).ceil().getInfo()

#                     for i in range(num_chunks):
#                         # Slice the current chunk
#                         chunk = dam_list.slice(i * chunk_size, (i + 1) * chunk_size)
#                         dam_chunk = ee.FeatureCollection(chunk)

                      
#                         S2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
#                         S2_cloud_filter = process_Sentinel2_with_cloud_coverage(S2)

#                         selected_datasets = st.session_state.selected_datasets
#                         Hydro = st.session_state.selected_waterway

#                         S2_chunk_export = ee.ImageCollection(S2_PixelExtraction_Export(dam_chunk, S2_cloud_filter, Hydro, selected_datasets))

#                         # Generate filenames for the current chunk
#                         S2_filename_id = S2_chunk_export.aggregate_array("Full_id").getInfo()

#                         # Export the current chunk
#                         geemap.ee_export_image_collection(
#                             S2_chunk_export,
#                             filenames=S2_filename_id,
#                             out_dir=export_dir,
#                             scale=5  # Adjust scale as needed
#                         )

#                         st.success(f"Chunk {i+1}/{num_chunks} exported successfully!")

#                     st.success("All chunks have been exported successfully!")
#                 except Exception as e:
#                     st.error(f"An error occurred during the export process: {e}")




