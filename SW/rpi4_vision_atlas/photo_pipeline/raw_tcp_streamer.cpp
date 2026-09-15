#include "raw_tcp_streamer.hpp"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <sys/socket.h>
#include <unistd.h>

#include <opencv2/imgproc.hpp>

namespace {

constexpr int kStreamWidth = 320;
constexpr int kStreamHeight = 240;

bool set_nonblocking(int fd) {
    const int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
        return false;
    }

    return fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

}  // namespace

RawTcpStreamer::RawTcpStreamer(std::uint16_t port)
    : port_(port) {}

RawTcpStreamer::~RawTcpStreamer() {
    close();
}

bool RawTcpStreamer::start() {
    if (server_fd_ >= 0) {
        return true;
    }

    server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd_ < 0) {
        std::cerr << "[camera stream] socket failed: "
                  << std::strerror(errno) << '\n';
        return false;
    }

    int reuse = 1;
    setsockopt(
        server_fd_,
        SOL_SOCKET,
        SO_REUSEADDR,
        &reuse,
        sizeof(reuse)
    );

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons(port_);

    if (bind(
            server_fd_,
            reinterpret_cast<sockaddr*>(&address),
            sizeof(address)
        ) < 0) {
        std::cerr << "[camera stream] bind failed: "
                  << std::strerror(errno) << '\n';
        close();
        return false;
    }

    if (listen(server_fd_, 1) < 0) {
        std::cerr << "[camera stream] listen failed: "
                  << std::strerror(errno) << '\n';
        close();
        return false;
    }

    if (!set_nonblocking(server_fd_)) {
        close();
        return false;
    }

    std::cout << "[camera stream] RAW RGBA listening on TCP "
              << port_ << '\n';

    return true;
}

void RawTcpStreamer::acceptClient() {
    if (server_fd_ < 0 || client_fd_ >= 0) {
        return;
    }

    const int fd = accept(server_fd_, nullptr, nullptr);

    if (fd < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            std::cerr << "[camera stream] accept failed: "
                      << std::strerror(errno) << '\n';
        }
        return;
    }

    if (!set_nonblocking(fd)) {
        ::close(fd);
        return;
    }

    client_fd_ = fd;
    pending_.clear();
    pending_offset_ = 0;

    std::cout << "[camera stream] client connected\n";
}

void RawTcpStreamer::disconnectClient() {
    if (client_fd_ >= 0) {
        ::close(client_fd_);
        client_fd_ = -1;
    }

    pending_.clear();
    pending_offset_ = 0;

    std::cout << "[camera stream] client disconnected\n";
}

void RawTcpStreamer::flushPending() {
    if (client_fd_ < 0 || pending_.empty()) {
        return;
    }

    while (pending_offset_ < pending_.size()) {
        const ssize_t sent = send(
            client_fd_,
            pending_.data() + pending_offset_,
            pending_.size() - pending_offset_,
            MSG_NOSIGNAL
        );

        if (sent > 0) {
            pending_offset_ += static_cast<std::size_t>(sent);
            continue;
        }

        if (sent < 0 &&
            (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return;
        }

        disconnectClient();
        return;
    }

    pending_.clear();
    pending_offset_ = 0;
}

void RawTcpStreamer::sendFrame(const cv::Mat& frame) {
    if (server_fd_ < 0 || frame.empty()) {
        return;
    }

    acceptClient();

    if (client_fd_ < 0) {
        return;
    }

    flushPending();

    // 이전 프레임이 아직 전송 중이면 새 프레임을 버린다.
    // 지연 누적 방지.
    if (!pending_.empty()) {
        return;
    }

    cv::Mat resized;
    cv::resize(
        frame,
        resized,
        cv::Size(kStreamWidth, kStreamHeight)
    );

    cv::Mat rgba;
    cv::cvtColor(
        resized,
        rgba,
        cv::COLOR_BGR2RGBA
    );

    const std::uint32_t payload_size =
        static_cast<std::uint32_t>(
            rgba.total() * rgba.elemSize()
        );

    const std::uint32_t network_size =
        htonl(payload_size);

    pending_.resize(
        sizeof(network_size) + payload_size
    );

    std::memcpy(
        pending_.data(),
        &network_size,
        sizeof(network_size)
    );

    std::memcpy(
        pending_.data() + sizeof(network_size),
        rgba.data,
        payload_size
    );

    pending_offset_ = 0;
    flushPending();
}

void RawTcpStreamer::close() {
    if (client_fd_ >= 0) {
        ::close(client_fd_);
        client_fd_ = -1;
    }

    if (server_fd_ >= 0) {
        ::close(server_fd_);
        server_fd_ = -1;
    }

    pending_.clear();
    pending_offset_ = 0;
}
