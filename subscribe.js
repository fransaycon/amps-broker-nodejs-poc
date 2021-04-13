const amps = require('amps')

async function subscribe() {
    const c = new amps.Client('subscriber')

    try {
        // Connect and logon
        await c.connect('ws://localhost:9007/amps/json')

        // Subscribe
        await c.subscribe(
            m => console.log('Received message: ' + m.data),
            'test'
        )
    }
    catch (err) { console.error(err) }
}

subscribe()
