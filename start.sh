#!/usr/bin/env bash
# Launch both dashboards and open the entry point
cd "$(dirname "$0")"

echo "Starting Red Hat Associates Platform..."
echo ""

# Kill any existing instances
pkill -f "streamlit run app1.py" 2>/dev/null
pkill -f "streamlit run app2.py" 2>/dev/null
sleep 1

# Start both apps in background
streamlit run app1.py --server.port 8501 --server.headless true &
PID1=$!
streamlit run app2.py --server.port 8502 --server.headless true &
PID2=$!

echo "✓ Customer Dashboard  → http://localhost:8501"
echo "✓ Associates Dashboard → http://localhost:8502"
echo ""
echo "➜ Open http://localhost:8501 to get started"
echo ""
echo "Press Ctrl+C to stop both dashboards"

trap "kill $PID1 $PID2 2>/dev/null; echo ''; echo 'Dashboards stopped.'; exit 0" INT TERM
wait
