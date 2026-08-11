FROM node:22-alpine

WORKDIR /app

# `npm ci` rather than `npm install`: it installs exactly the lock file, which
# is what makes the container and the CI agree on versions.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
