const amps = require('amps')

async function publish() {
    const c = new amps.Client('publisher')

    try {
        // Connect and logon
        await c.connect('ws://127.0.0.1:9007/amps/json')

        // Publish
        c.publish('test', { message: 'Hello, world!' })
    }
    catch (err) { console.error(err) }
}

publish()

