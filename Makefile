.PHONY: help build up down logs restart clean init-data

help:
	@echo "Available commands:"
	@echo "  make build      - Build Docker images"
	@echo "  make up         - Start containers"
	@echo "  make down       - Stop containers"
	@echo "  make logs       - View logs"
	@echo "  make restart    - Restart containers"
	@echo "  make clean      - Remove containers and volumes"
	@echo "  make init-data  - Initialize data (fetch last 3 days)"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

restart:
	docker-compose restart

clean:
	docker-compose down -v
	docker-compose rm -f

init-data:
	docker-compose exec backend python init_data.py 3

stop:
	docker-compose stop

start:
	docker-compose start

