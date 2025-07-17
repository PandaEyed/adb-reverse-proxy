#/usr/bin/env python3
import asyncio
import struct
import binascii
import logging

logger = logging.getLogger(__name__)

async def send_cmd(writer, cmd, arg0, arg1, data=b""):
    if isinstance(data, str):
        data = data.encode()
    cmd_id, = struct.unpack("<I", cmd)
    header = struct.pack("<IIIIII", cmd_id, arg0, arg1, len(data), binascii.crc32(data), cmd_id ^ 0xFFFFFFFF)
    writer.write(header + data)
    await writer.drain()

async def recv_cmd(reader):
    header = await reader.readexactly(24)
    cmd_id, arg0, arg1, data_len, crc32, magic = struct.unpack("<IIIIII", header)
    if cmd_id != magic ^ 0xFFFFFFFF:
        raise Exception("Magic mismatch")
    data = await reader.readexactly(data_len)
    return header[:4], arg0, arg1, data

class ProxyChannel:
    def __init__(self, proxy, name, local_id, remote_id, reader, writer):
        self.proxy = proxy
        self.name = name
        self.local_id = local_id
        self.remote_id = remote_id
        self.reader = reader
        self.writer = writer
        self.closed = False
        self.ready_to_send = asyncio.Semaphore(0)
        self.sink_task = asyncio.create_task(self.sink())
        # Start with one ready signal to begin reading
        self.ready()

    async def write(self, data):
        logger.debug(f"Channel {self.name}: Writing {len(data)} bytes to device")
        try:
            self.writer.write(data)
            await self.writer.drain()
            logger.debug(f"Channel {self.name}: Sending OKAY")
            await self.proxy.send_cmd(b"OKAY", self.remote_id, self.local_id)
        except Exception as e:
            logger.error(f"Channel {self.name}: Write error: {e}")
            await self.close()

    def ready(self):
        self.ready_to_send.release()

    async def sink(self):
        logger.debug(f"Channel {self.name}: Starting sink")
        try:
            while not self.closed:
                await self.ready_to_send.acquire()
                if self.closed:
                    break
                logger.debug(f"Channel {self.name}: Reading from device")
                try:
                    data = await self.reader.read(self.proxy.max_data_len)
                    if not data:
                        logger.debug(f"Channel {self.name}: EOF from device")
                        # For shell commands, don't immediately close on EOF
                        # The process might still be running
                        if self.name.startswith('shell:'):
                            logger.debug(f"Channel {self.name}: Shell EOF, waiting for explicit close")
                            await asyncio.sleep(0.1)
                            continue
                        break
                    logger.debug(f"Channel {self.name}: Sending WRTE with {len(data)} bytes")
                    await self.proxy.send_cmd(b"WRTE", self.remote_id, self.local_id, data)
                except Exception as e:
                    logger.error(f"Channel {self.name}: Read error: {e}")
                    break
        except Exception as e:
            logger.error(f"Channel {self.name}: Sink error: {e}")
        finally:
            if not self.closed:
                await self.close()

    async def close(self):
        if not self.closed:
            logger.debug(f"Channel {self.name}: Closing")
            self.closed = True
            self.ready_to_send.release()  # Release any waiting sink
            if not self.sink_task.done():
                self.sink_task.cancel()
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
            await self.proxy.send_cmd(b"CLSE", self.remote_id, self.local_id)

async def open_client_stream(adb_addr, device_id, destination):
    logger.debug(f"Opening stream to {destination} for device {device_id}")
    reader, writer = await asyncio.open_connection(*adb_addr)
    logger.debug("Connected to local ADB")
    for cmd in [f"host:transport:{device_id}", destination]:
        cmd_b = cmd.encode()
        writer.write(f"{len(cmd_b):04x}".encode() + cmd_b)
        await writer.drain()
        logger.debug(f"Sent command: {cmd}")
        status = await reader.readexactly(4)
        logger.debug(f"Received status: {status}")
        if status != b"OKAY":
            try:
                len_b = await reader.readexactly(4)
                err = await reader.readexactly(int(len_b, 16))
                logger.error(f"Error response: {err.decode()}")
                writer.close()
                raise Exception(f"Failed: {err.decode()}")
            except:
                writer.close()
                raise Exception(f"Failed to open {destination}")
    logger.debug("Stream opened successfully")
    return reader, writer

async def list_adb_devices(adb_addr):
    reader, writer = await asyncio.open_connection(*adb_addr)
    cmd = b"host:devices"
    writer.write(f"{len(cmd):04x}".encode() + cmd)
    await writer.drain()
    status = await reader.readexactly(4)
    if status != b"OKAY":
        raise Exception("Failed")
    len_str = await reader.readexactly(4)
    data = await reader.readexactly(int(len_str, 16))
    writer.close()
    lines = data.decode().splitlines()
    return [line.split("\t")[0] for line in lines if line.endswith("\tdevice")]

class AdbDeviceProxy:
    def __init__(self, reader, writer, device_id, adb_addr):
        self.reader = reader
        self.writer = writer
        self.device_id = device_id
        self.adb_addr = adb_addr
        self.protocol_version = 0x01000000
        self.max_data_len = 256 * 1024
        self.device_name = f"proxy_{device_id}"
        self.streams = {}
        self.next_remote_id = 1

    async def send_cmd(self, *args):
        await send_cmd(self.writer, *args)

    async def recv_cmd(self):
        return await recv_cmd(self.reader)

    async def run(self):
        logger.info(f"Proxy for {self.device_id}: Starting")
        cmd, arg0, arg1, data = await self.recv_cmd()
        logger.debug(f"Proxy for {self.device_id}: Received {cmd}")
        if cmd != b"CNXN":
            raise Exception(f"Expected CNXN, got {cmd}")
        await self.send_cmd(b"CNXN", self.protocol_version, self.max_data_len, f"device::{self.device_name}\0".encode())
        while True:
            cmd, local_id, remote_id, data = await self.recv_cmd()
            logger.debug(f"Proxy for {self.device_id}: Received {cmd} local_id={local_id} remote_id={remote_id} data_len={len(data)}")
            if cmd == b"OPEN":
                destination = data.rstrip(b"\0").decode()
                remote_id = self.next_remote_id
                self.next_remote_id += 1
                logger.info(f"Proxy for {self.device_id}: Opening channel to {destination}")
                try:
                    s_reader, s_writer = await open_client_stream(self.adb_addr, self.device_id, destination)
                    channel = ProxyChannel(self, destination, local_id, remote_id, s_reader, s_writer)
                    self.streams[remote_id] = channel
                    await self.send_cmd(b"OKAY", remote_id, local_id)
                    logger.debug(f"Successfully opened channel {remote_id} for {destination}")
                except Exception as e:
                    logger.warning(f"Failed to open {destination}: {e}")
                    await self.send_cmd(b"CLSE", local_id, 0)
            elif cmd == b"WRTE":
                channel = self.streams.get(remote_id)
                if channel:
                    await channel.write(data)
            elif cmd == b"OKAY":
                channel = self.streams.get(remote_id)
                if channel:
                    logger.debug(f"Proxy for {self.device_id}: Received OKAY for channel {remote_id}")
                    channel.ready()
            elif cmd == b"CLSE":
                channel = self.streams.get(remote_id)
                if channel:
                    logger.debug(f"Proxy for {self.device_id}: Closing channel {remote_id} ({channel.name})")
                    await channel.close()
                    del self.streams[remote_id]
                else:
                    # Send CLSE response for unknown channel
                    logger.debug(f"Proxy for {self.device_id}: Received CLSE for unknown channel {remote_id}")
                    await self.send_cmd(b"CLSE", local_id, 0)

async def handle_connection(device_id, adb_addr, reader, writer):
    try:
        proxy = AdbDeviceProxy(reader, writer, device_id, adb_addr)
        await proxy.run()
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        writer.close()

class ScrcpyTcpProxy:
    def __init__(self, device_id, adb_addr, scrcpy_port):
        self.device_id = device_id
        self.adb_addr = adb_addr
        self.scrcpy_port = scrcpy_port
        self.connections = []
        self.server_started = False
        
    async def ensure_scrcpy_server_running(self):
        """Ensure scrcpy server is running on the device"""
        if self.server_started:
            return
            
        try:
            logger.info(f"Starting scrcpy server on device {self.device_id}")
            
            # Connect to ADB
            adb_reader, adb_writer = await asyncio.open_connection(*self.adb_addr)
            
            # Setup transport to device
            transport_cmd = f"host:transport:{self.device_id}"
            cmd_b = transport_cmd.encode()
            adb_writer.write(f"{len(cmd_b):04x}".encode() + cmd_b)
            await adb_writer.drain()
            
            status = await adb_reader.readexactly(4)
            if status != b"OKAY":
                logger.error(f"Failed to setup transport for scrcpy server start: {status}")
                adb_writer.close()
                return
            
            # Start scrcpy server with tunnel_forward=true
            server_cmd = "shell:CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / com.genymobile.scrcpy.Server 3.3.1 tunnel_forward=true log_level=info"
            cmd_b = server_cmd.encode()
            adb_writer.write(f"{len(cmd_b):04x}".encode() + cmd_b)
            await adb_writer.drain()
            
            status = await adb_reader.readexactly(4)
            if status != b"OKAY":
                logger.error(f"Failed to start scrcpy server: {status}")
                adb_writer.close()
                return
                
            logger.info(f"Scrcpy server command sent, waiting for startup...")
            
            # Wait a bit for the server to start up
            await asyncio.sleep(2)
            
            # Keep the shell connection alive in background
            asyncio.create_task(self._keep_server_alive(adb_reader, adb_writer))
            
            self.server_started = True
            logger.info(f"Scrcpy server should be running on device {self.device_id}")
            
        except Exception as e:
            logger.error(f"Failed to start scrcpy server on {self.device_id}: {e}")
            
    async def _keep_server_alive(self, adb_reader, adb_writer):
        """Keep the scrcpy server shell session alive"""
        try:
            # Read any output from the server to keep connection alive
            while True:
                try:
                    data = await asyncio.wait_for(adb_reader.read(1024), timeout=1.0)
                    if not data:
                        break
                    # Log server output for debugging
                    if data.strip():
                        logger.debug(f"Scrcpy server output: {data.decode('utf-8', errors='ignore').strip()}")
                except asyncio.TimeoutError:
                    # No data received, continue to keep connection alive
                    continue
        except Exception as e:
            logger.debug(f"Scrcpy server session ended: {e}")
        finally:
            try:
                adb_writer.close()
            except:
                pass
            self.server_started = False
        
    async def handle_scrcpy_connection(self, reader, writer):
        """Handle scrcpy TCP connections (video/audio/control streams)"""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"Scrcpy connection from {client_addr} for device {self.device_id}")
        
        adb_reader = None
        adb_writer = None
        
        try:
            # First, ensure scrcpy server is running on device
            await self.ensure_scrcpy_server_running()
            
            # Create reverse connection to device's localabstract:scrcpy
            logger.debug(f"Connecting to ADB at {self.adb_addr}")
            adb_reader, adb_writer = await asyncio.open_connection(*self.adb_addr)
            logger.debug("Connected to ADB successfully")
            
            # Setup transport to device
            transport_cmd = f"host:transport:{self.device_id}"
            cmd_b = transport_cmd.encode()
            adb_writer.write(f"{len(cmd_b):04x}".encode() + cmd_b)
            await adb_writer.drain()
            logger.debug(f"Sent transport command: {transport_cmd}")
            
            status = await adb_reader.readexactly(4)
            logger.debug(f"Transport status: {status}")
            if status != b"OKAY":
                logger.error(f"Failed to setup transport for {self.device_id}, status: {status}")
                return
                
            # Connect to localabstract:scrcpy on device
            scrcpy_cmd = "localabstract:scrcpy"
            cmd_b = scrcpy_cmd.encode()
            adb_writer.write(f"{len(cmd_b):04x}".encode() + cmd_b)
            await adb_writer.drain()
            logger.debug(f"Sent scrcpy command: {scrcpy_cmd}")
            
            status = await adb_reader.readexactly(4)
            logger.debug(f"Scrcpy socket status: {status}")
            if status != b"OKAY":
                logger.error(f"Failed to connect to scrcpy socket on {self.device_id}, status: {status}")
                return
                
            logger.info(f"Scrcpy TCP tunnel established for {self.device_id}")
            
            # Bidirectional data forwarding
            async def forward_data(src_reader, dst_writer, direction):
                try:
                    bytes_transferred = 0
                    while True:
                        data = await src_reader.read(8192)
                        if not data:
                            logger.debug(f"Scrcpy {direction}: EOF reached, {bytes_transferred} bytes transferred")
                            break
                        dst_writer.write(data)
                        await dst_writer.drain()
                        bytes_transferred += len(data)
                        if bytes_transferred % 100000 == 0:  # Log every 100KB
                            logger.debug(f"Scrcpy {direction}: {bytes_transferred} bytes transferred")
                except Exception as e:
                    logger.debug(f"Scrcpy {direction} forwarding ended: {e}")
                finally:
                    try:
                        dst_writer.close()
                    except:
                        pass
            
            # Start bidirectional forwarding
            logger.debug("Starting bidirectional data forwarding")
            await asyncio.gather(
                forward_data(reader, adb_writer, "client->device"),
                forward_data(adb_reader, writer, "device->client"),
                return_exceptions=True
            )
            
        except Exception as e:
            logger.error(f"Scrcpy connection error for {self.device_id}: {e}")
        finally:
            try:
                writer.close()
            except:
                pass
            try:
                if adb_writer is not None:
                    adb_writer.close()
            except:
                pass
            logger.info(f"Scrcpy connection closed for {self.device_id}")

async def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    adb_addr = ("localhost", 5037)
    try:
        devices = await list_adb_devices(adb_addr)
        if not devices:
            print("No devices found")
            return
        
        adb_base_port = 6000
        scrcpy_base_port = 7000
        servers = []
        
        print(f"Found {len(devices)} device(s)")
        print("\n=== ADB Proxy Ports ===")
        
        for idx, device_id in enumerate(devices):
            adb_port = adb_base_port + idx
            scrcpy_port = scrcpy_base_port + idx
            
            # Start ADB proxy server
            adb_server = await asyncio.start_server(
                lambda r, w, dev=device_id: handle_connection(dev, adb_addr, r, w), 
                "0.0.0.0", 
                adb_port
            )
            servers.append(adb_server)
            
            # Start Scrcpy TCP proxy server
            scrcpy_proxy = ScrcpyTcpProxy(device_id, adb_addr, scrcpy_port)
            scrcpy_server = await asyncio.start_server(
                scrcpy_proxy.handle_scrcpy_connection,
                "0.0.0.0",
                scrcpy_port
            )
            servers.append(scrcpy_server)
            logger.info(f"Scrcpy TCP proxy started on port {scrcpy_port} for device {device_id}")
            
            print(f"Device: {device_id}")
            print(f"  ADB Port: {adb_port} (adb connect <server_ip>:{adb_port})")
            print(f"  Scrcpy Port: {scrcpy_port} (for scrcpy TCP streams)")
            print()
        
        print("=== Usage Instructions ===")
        print("1. Connect ADB: adb connect <server_ip>:<adb_port>")
        print("2. Run scrcpy with TCP tunnel: scrcpy --tunnel-host=<server_ip> --tunnel-port=<scrcpy_port>")
        print("   Note: The proxy will automatically start the scrcpy server on the device")
        print("\nProxy servers started. Press Ctrl+C to stop.")
        
        await asyncio.gather(*(s.serve_forever() for s in servers))
    except KeyboardInterrupt:
        print("\nShutting down proxy servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
