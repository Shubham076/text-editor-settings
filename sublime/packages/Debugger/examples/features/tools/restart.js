// Native restart: start "Restart in place (node)", then press the restart button.
//
// Expected: the console prints "Restarted" and a new "started" line with a new pid,
// and the session is not torn down and rebuilt in between.

const started = new Date().toLocaleTimeString();
console.log(`started at ${started}, pid ${process.pid}`);

let tick = 0;
setInterval(() => {
	tick += 1;
	console.log(`tick ${tick} (started at ${started})`);
}, 2000);
