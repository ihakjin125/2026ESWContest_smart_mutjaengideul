#pragma once

#include <cstdint>
#include <vector>

#include <opencv2/core.hpp>

class RawTcpStreamer {
public:
    explicit RawTcpStreamer(std::uint16_t port);
    ~RawTcpStreamer();

    RawTcpStreamer(const RawTcpStreamer&) = delete;
    RawTcpStreamer& operator=(const RawTcpStreamer&) = delete;

    bool start();
    void sendFrame(const cv::Mat& frame);
    void close();

private:
    void acceptClient();
    void disconnectClient();
    void flushPending();

    std::uint16_t port_;
    int server_fd_ = -1;
    int client_fd_ = -1;

    std::vector<unsigned char> pending_;
    std::size_t pending_offset_ = 0;
};
