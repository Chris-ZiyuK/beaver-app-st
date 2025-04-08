import streamlit as st
st.set_page_config(layout="wide")

# Place the logo at the top
st.sidebar.image("assets/pngimg.com - beaver_PNG35.png")

about_page = st.Page(
    page = "pages/About_Lab.py",
    title = "About Me!",
    icon = ":material/account_circle:",
    default = True,
)

project_1_page = st.Page(
    page = "pages/Exports_page.py",
    title = "Export Images!",
    icon = ":material/bar_chart:",

)

project_2_page = st.Page(
    page = "pages/Quick_analysis.py",
    title = "Quickly visualize!",
    icon = ":material/bar_chart:",

)


pg = st.navigation(pages= [about_page,project_1_page,project_2_page])
# st.logo("assets\pngimg.com - beaver_PNG35.png")
pg.run()

# test 