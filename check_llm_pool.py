import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'src'))
# Suppress print from import
import io
original_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from llm_helper import model_selector
except Exception as e:
    sys.stdout = original_stdout
    print(f"Import Error: {e}")
    sys.exit(1)
sys.stdout = original_stdout

print(f"Total Models: {len(model_selector.pool)}")
print(f"Total Capacity: {model_selector.get_total_capacity()}")
for m in model_selector.pool:
    print(f"- {m['name']} (Limit: {model_selector.limits[m['name']]})")
