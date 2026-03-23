openapi: 3.0.1
info:
  title: HOPEFX API
  description: This is the API documentation for HOPEFX, an AI trading platform.
  version: 1.0.0
servers:
  - url: https://api.hopefx.com/v1
paths:
  /auth/login:
    post:
      summary: User login
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                username:
                  type: string
                password:
                  type: string
      responses:
        '200':
          description: Login successful
          content:
            application/json:
              schema:
                type: object
                properties:
                  token:
                    type: string
        '401':
          description: Invalid credentials

  /market_data/prices:
    get:
      summary: Get market prices
      parameters:
        - in: query
          name: symbol
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Successful response
          content:
            application/json:
              schema:
                type: object
                properties:
                  symbol:
                    type: string
                  price:
                    type: number

  /trading/orders:
    post:
      summary: Place a new order
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                type:
                  type: string
                symbol:
                  type: string
                quantity:
                  type: number
      responses:
        '201':
          description: Order created
          content:
            application/json:
              schema:
                type: object
                properties:
                  orderId:
                    type: string

  /portfolio:
    get:
      summary: Get portfolio details
      responses:
        '200':
          description: Portfolio details retrieved
          content:
            application/json:
              schema:
                type: object
                properties:
                  totalValue:
                    type: number
                  positions:
                    type: array
                    items:
                      type: object
                      properties:
                        symbol:
                          type: string
                        quantity:
                          type: number

  /backtesting/run:
    post:
      summary: Run a backtest
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                strategyId:
                  type: string
                startDate:
                  type: string
                  format: date
                endDate:
                  type: string
                  format: date
      responses:
        '200':
          description: Backtest results
          content:
            application/json:
              schema:
                type: object
                properties:
                  results:
                    type: object

  /risk_management:
    post:
      summary: Set risk management rules
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                maxDrawdown:
                  type: number
                maxPositionSize:
                  type: number
      responses:
        '200':
          description: Risk management rules set
