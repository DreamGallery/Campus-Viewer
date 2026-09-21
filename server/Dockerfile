FROM node:22-alpine
WORKDIR /app
COPY server/app.mjs server/resources.mjs ./server/
USER node
EXPOSE 8787
CMD ["node", "server/app.mjs"]
