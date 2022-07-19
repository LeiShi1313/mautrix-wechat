import re


class ImageDecodeError(Exception):
    pass

class WechatImageDecoder:

    @classmethod
    def decode(cls, dat_file) -> str | None:
        decoder = cls._get_decoder(dat_file)
        return decoder(dat_file)

    @classmethod
    def _get_decoder(cls, dat_file):
        decoders = {
            r'.+\.dat$': cls._decode_pc_dat,
            r'cache\.data\.\d+$': cls._decode_android_dat,
        }

        for k, v in decoders.items():
            if re.match(k, dat_file):
                return v
        return cls._decode_unknown_dat

    @classmethod
    def _decode_pc_dat(cls, dat_file):
        
        def do_magic(header_code, buf):
            return header_code ^ list(buf)[0] if buf else 0x00
        
        def decode(magic, buf):
            return bytearray([b ^ magic for b in list(buf)])
            
        def guess_encoding(buf):
            headers = {
                'jpg': (0xff, 0xd8),
                'png': (0x89, 0x50),
                'gif': (0x47, 0x49),
            }
            for encoding in headers:
                header_code, check_code = headers[encoding] 
                magic = do_magic(header_code, buf)
                _, code = decode(magic, buf[:2])
                if check_code == code:
                    return (encoding, magic)
            raise ImageDecodeError('Magic guess failed')

        with open(dat_file, 'rb') as f:
            buf = bytearray(f.read())
        file_type, magic = guess_encoding(buf)

        img_file = re.sub(r'.dat$', '.' + file_type, dat_file)
        with open(img_file, 'wb') as f:
            new_buf = decode(magic, buf)
            f.write(new_buf)
        return img_file

    @classmethod
    def _decode_android_dat(cls, dat_file):
        with open(dat_file, 'rb') as f:
            buf = f.read()

        last_index = 0
        imgfile = None
        for i, m in enumerate(re.finditer(b'\xff\xd8\xff\xe0\x00\x10\x4a\x46', buf)):
            if m.start() == 0:
                continue

            imgfile = '%s_%d.jpg' % (dat_file, i)
            with open(imgfile, 'wb') as f:
                f.write(buf[last_index: m.start()])
            last_index = m.start()
        return imgfile

    @classmethod
    def _decode_unknown_dat(cls, dat_file):
        raise ImageDecodeError(f'Unknown file type: {dat_file}')


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print('\n'.join([
            'Usage:',
            '  python WechatImageDecoder.py [dat_file]',
            '',
            'Example:',
            '  # PC:',
            '  python WechatImageDecoder.py 1234567890.dat',
            '',
            '  # Android:',
            '  python WechatImageDecoder.py cache.data.10'
        ]))
        sys.exit(1)

    _,  dat_file = sys.argv[:2]
    try:
        WechatImageDecoder(dat_file)
    except Exception as e:
        print(e)
        sys.exit(1)
    sys.exit(0)