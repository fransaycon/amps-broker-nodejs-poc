# AMPS-POC

## Prerequisites
Docker should be installed

## Installation
1. Build the docker container
```
docker build ./amps-docker -t <anything container name you want>
```

2. Run the docker container
```
docker run -p 8085:8085 -p 9007:9007 -p 9008:9008 <the container name you chose>
```

3. Install node definitions
```
yarn
```

4. Run the scripts
```
node subcribe.js 
node publish.js
```

Notes: current using this release https://devnull.crankuptheamps.com/releases/amps/5.3.0.259/AMPS-5.3.0.259-Release-Linux.tar.gz. Change this definition in the Dockerfile accordingly in ./amps-docker.
