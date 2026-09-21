FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig*.json postcss.config.js tailwind.config.js ./
COPY src ./src
COPY public/theme-init.js ./public/theme-init.js
COPY public/images ./public/images
COPY public/fonts/*LICENSE.txt ./public/fonts/
RUN npm run build

FROM nginx:stable-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
