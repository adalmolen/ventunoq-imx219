/* RGB-only image processing. No device, kernel, filesystem or network access. */
#include <stddef.h>
#include <stdint.h>
#include <pthread.h>

struct job {
    const uint8_t *src, *lut;
    uint8_t *dst;
    int width, height, first, last, saturation, noise;
};

static void *process(void *argument)
{
    struct job *j = argument;
    const size_t row = (size_t)j->width * 3;
    for (int y = j->first; y < j->last; ++y) {
        const uint8_t *current = j->src + (size_t)y * row;
        const uint8_t *above = y ? current - row : current;
        const uint8_t *below = y + 1 < j->height ? current + row : current;
        uint8_t *output = j->dst + (size_t)y * row;
        for (int x = 0; x < j->width; ++x) {
            int rgb[3];
            const size_t at = (size_t)x * 3;
            const size_t left = x ? at - 3 : at;
            const size_t right = x + 1 < j->width ? at + 3 : at;
            for (int c = 0; c < 3; ++c) {
                unsigned value = current[at + c];
                if (j->noise) {
                    const unsigned smooth = (value * 4 + above[at+c] + below[at+c] +
                                             current[left+c] + current[right+c] + 4) >> 3;
                    value = (smooth * (unsigned)j->noise + value * (unsigned)(256-j->noise) + 128) >> 8;
                }
                rgb[c] = j->lut[c * 256 + value];
            }
            const int luma = (77 * rgb[0] + 150 * rgb[1] + 29 * rgb[2] + 128) >> 8;
            for (int c = 0; c < 3; ++c) {
                const int scaled = j->saturation * rgb[c] + (256-j->saturation) * luma + 128;
                int value = scaled > 0 ? scaled >> 8 : 0;
                output[at+c] = (uint8_t)(value > 255 ? 255 : value);
            }
        }
    }
    return NULL;
}

int picture_process(const uint8_t *source, size_t source_size,
                    uint8_t *output, size_t output_size,
                    int width, int height, const uint8_t *curves, size_t curves_size,
                    int saturation, int noise, int threads)
{
    if (!source || !output || !curves || source == output || width < 1 || height < 1 ||
        width > 8192 || height > 8192 || (size_t)width * (size_t)height > 16777216 ||
        source_size != (size_t)width * (size_t)height * 3 || output_size != source_size ||
        curves_size != 768 || saturation < 256 || saturation > 461 ||
        noise < 0 || noise > 256 || threads < 1 || threads > 2)
        return -1;
    struct job main_job = {source, curves, output, width, height, 0, height, saturation, noise};
    if (threads == 2 && height >= 32) {
        struct job worker_job = main_job;
        worker_job.last = height / 2;
        pthread_t worker;
        if (pthread_create(&worker, NULL, process, &worker_job) == 0) {
            main_job.first = worker_job.last;
            process(&main_job);
            if (pthread_join(worker, NULL) != 0)
                return -2;
            return 0;
        }
    }
    process(&main_job);
    return 0;
}
