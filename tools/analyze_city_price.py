import pandas as pd
import glob
import os
import sys

def get_latest_excel():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = glob.glob(os.path.join(base_dir, 'fapaifang_data_*.xlsx'))
    # Filter out trend files
    files = [f for f in files if not f.endswith('_trend.xlsx')]
    if not files:
        return None
    # Sort by modification time
    return max(files, key=os.path.getmtime)

def analyze_prices(file_path):
    print(f"[INFO] Reading {file_path}...")
    try:
        df = pd.read_excel(file_path, engine='openpyxl')
    except Exception as e:
        print(f"[ERROR] Failed to read Excel: {e}")
        return

    # Check required columns
    required = ['城市', '交易时间', '单价']
    if not all(col in df.columns for col in required):
        print(f"[ERROR] Missing required columns: {required}")
        print(f"Available columns: {df.columns.tolist()}")
        return

    # Filter invalid data
    df = df.dropna(subset=['城市', '交易时间', '单价'])
    df = df[df['单价'] > 0]

    # Convert Date
    # Try parsing mixed formats (YYYY/MM/DD or YYYY-MM-DD)
    # Some dates might be ranges "2021/12/24 10:00至2022/02/22 10:00" -> Take the first part
    def parse_date(x):
        try:
            str_val = str(x).split('至')[0].strip()
            return pd.to_datetime(str_val).strftime('%Y-%m')
        except:
            return None

    df['Month'] = df['交易时间'].apply(parse_date)
    df = df.dropna(subset=['Month'])

    # Group by City + Month
    # Count, Mean Price
    result = df.groupby(['城市', 'Month'])['单价'].agg(['count', 'mean']).reset_index()
    result['mean'] = result['mean'].round(2)
    result.rename(columns={'count': '成交量', 'mean': '平均单价'}, inplace=True)

    # Sort
    result.sort_values(by=['城市', 'Month'], inplace=True)

    # --- Chart Generation ---
    from openpyxl import load_workbook
    from openpyxl.chart import LineChart, Reference

    # Identiy Top 10 cities by volume
    top_cities = df['城市'].value_counts().head(10).index.tolist()
    print(f"[INFO] Generating chart for Top 10 cities: {top_cities}")
    
    # Filter & Pivot for Chart Data
    chart_df = df[df['城市'].isin(top_cities)]
    pivot_df = chart_df.pivot_table(index='Month', columns='城市', values='单价', aggfunc='mean').round(2)
    pivot_df.sort_index(inplace=True)
    
    # OUTPUT
    output_file = file_path.replace('.xlsx', '_trend.xlsx')

    # Save to Excel with multiple sheets
    print(f"[INFO] Saving analysis to {output_file}...")
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        result.to_excel(writer, sheet_name='All_Data', index=False)
        pivot_df.to_excel(writer, sheet_name='Top10_Trend')
        
        # Access workbook and sheet to add chart
        workbook = writer.book
        worksheet = writer.sheets['Top10_Trend']
        
        # Create Line Chart
        chart = LineChart()
        chart.title = "Top 10 Cities Price Trend"
        chart.style = 13
        chart.y_axis.title = 'Average Unit Price (CNY/m²)'
        chart.x_axis.title = 'Month'
        chart.height = 15
        chart.width = 30

        # Data Range (including headers)
        # Rows: All rows in pivot_df + 1 (header)
        # Cols: Index col + 10 cities = 11 cols? No, index is A, cols are B...K
        # Min Row = 1 (header), Max Row = len(pivot_df) + 1
        # Min Col = 2 (first city), Max Col = len(top_cities) + 1
        data = Reference(worksheet, min_col=2, min_row=1, max_col=len(pivot_df.columns)+1, max_row=len(pivot_df)+1)
        cats = Reference(worksheet, min_col=1, min_row=2, max_row=len(pivot_df)+1)
        
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        
        # Place chart at A10 (below data sort of, or to the right? Let's put it to the right)
        # Actually pivot table size is small (12 months x 10 cols). Let's put chart at M2.
        worksheet.add_chart(chart, "M2")
        
    print(f"[SUCCESS] Analysis complete! Chart added to sheet 'Top10_Trend'.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        target_file = get_latest_excel()
        
    if target_file:
        analyze_prices(target_file)
    else:
        print("[ERROR] No 'fapaifang_data_*.xlsx' found.")
