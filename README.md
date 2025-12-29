#BitEver esplora 3#

pm2  <br>
run proxy.py <br>
<br>
pm2 start update_and_restart.sh --name "p2pk-full-update" --cron "0 0 * * *" --no-autorestart  <br>
run generate.py <br> 


proxy : esplora <-> python middle API <br>
every 10min refresh scan result <br>
