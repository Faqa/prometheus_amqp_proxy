import atexit
import logging
import threading

import pika
import prometheus_client


# TODO: Add prometheus counters in this file.


class _PrometheusMetricsServer(threading.Thread):

    def __init__(self, connection_params, exchange, routing_key):
        super().__init__()
        self._connection_params = connection_params
        self._exchange = exchange
        self._routing_key = routing_key
        self._connection = None
        self._channel = None
        self._close_event = threading.Event()
        # Connecting in ctor, so that an exception will be raised in case of bad parameters.
        self._connect()
        self._running = True

    def stop(self):
        try:
            self._running = False
            if self._connection.is_open:
                self._connection.close()
        finally:
            self._close_event.set()

    def run(self):
        while self._running:
            try:
                if not self._connection.is_open:
                    self._connect()
                self._amqp_loop()
            except:
                logging.exception("Exception in AMQP loop")
                if self._connection.is_open and self._running:
                    self._connection.close()

    def _connect(self):
        self._connection = pika.BlockingConnection(self._connection_params)
        self._channel = self._connection.channel()
        self._channel.exchange_declare(self._exchange, durable=True)
        self._channel.queue_declare(self._routing_key, auto_delete=True)
        self._channel.queue_bind(self._routing_key, self._exchange)

    def _amqp_loop(self):
        for method, props, unused_body in self._channel.consume(
                self._routing_key, exclusive=True, auto_ack=True):
            self._channel.basic_publish(
                "",
                props.reply_to,
                prometheus_client.generate_latest(prometheus_client.REGISTRY),
                pika.BasicProperties(correlation_id=props.correlation_id),
            )


def start_amqp_server(connection_params, exchange, routing_key):
    """Starts an AMQP server for prometheus metrics as a daemon thread."""
    t = _PrometheusMetricsServer(connection_params, exchange, routing_key)
    t.daemon = True
    def stop():
        t._connection.add_callback_threadsafe(t.stop)
        t._close_event.wait()
    atexit.register(stop)
    t.start()

